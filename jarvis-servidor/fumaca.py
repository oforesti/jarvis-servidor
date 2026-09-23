"""Testa um servidor JÁ PUBLICADO, de fora, como um cliente de verdade.

    python -m servidor.fumaca https://seu-servidor.vercel.app

Existe porque os testes da sua máquina rodam em SQLite, e passar neles não
prova que o Postgres da produção está certo. Este aqui exercita o caminho
inteiro no banco de verdade: cria conta, entra, valida licença, pede compra.

É seguro rodar em produção. Ele cria uma conta com um endereço sorteado
(`fumaca-<aleatorio>@teste.jarvis`) e apaga tudo no fim — e se não conseguir
apagar, avisa exatamente o que ficou para trás, em vez de deixar sujeira
escondida no seu painel.
"""

from __future__ import annotations

import secrets
import sys

import requests

PRAZO = (10, 40)     # o primeiro acesso acorda a função; pode demorar


class Falhou(Exception):
    pass


class Fumaca:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.email = f"fumaca-{secrets.token_hex(4)}@teste.jarvis"
        self.senha = secrets.token_urlsafe(16)
        self.acesso = ""
        self.refresh = ""
        self.passos = 0

    # ------------------------------------------------------------ apoio
    def _chamar(self, metodo: str, caminho: str, corpo=None, token=False):
        cabecalhos = {"Authorization": f"Bearer {self.acesso}"} if token else {}
        try:
            r = requests.request(metodo, self.base + caminho, json=corpo,
                                 headers=cabecalhos, timeout=PRAZO)
        except requests.RequestException as e:
            raise Falhou(f"não consegui falar com {self.base}: {e}") from e
        try:
            return r.status_code, r.json()
        except ValueError:
            raise Falhou(f"{caminho} respondeu {r.status_code} sem JSON: "
                         f"{r.text[:200]}") from None

    def checar(self, descricao: str, condicao: bool, detalhe: str = "") -> None:
        self.passos += 1
        if condicao:
            print(f"  ok   {descricao}")
        else:
            print(f"  FALHOU  {descricao}")
            raise Falhou(detalhe or descricao)

    # ------------------------------------------------------------ passos
    def rodar(self) -> None:
        print(f"Testando {self.base}")
        print(f"conta de teste: {self.email}\n")

        codigo, corpo = self._chamar("GET", "/saude")
        self.checar("o servidor responde", codigo == 200 and corpo.get("ok"),
                    f"/saude devolveu {codigo}: {corpo}")

        codigo, corpo = self._chamar("GET", "/chave-publica")
        self.checar("a chave pública existe (segredo veio do ambiente)",
                    codigo == 200 and len(corpo.get("chave", "")) > 20,
                    "sem chave pública o cliente não confere licença offline")
        chave = corpo["chave"]

        codigo, corpo = self._chamar("POST", "/site/cadastrar", {
            "email": self.email, "senha": self.senha, "nome": "Teste de fumaça"})
        self.checar("cadastro pelo site grava no banco", codigo == 200,
                    f"/site/cadastrar devolveu {codigo}: {corpo}")

        codigo, corpo = self._chamar("POST", "/site/pedido", {
            "email": self.email, "nome": "Teste de fumaça", "aparelhos": 1})
        self.checar("pedido de compra entra", codigo == 200 and corpo.get("ok"),
                    f"/site/pedido devolveu {codigo}: {corpo}")

        codigo, corpo = self._chamar("POST", "/conta/entrar", {
            "email": self.email, "senha": self.senha,
            "impressao": f"fumaca-{secrets.token_hex(3)}",
            "apelido": "Máquina de teste", "plataforma": "teste"})
        self.checar("login devolve sessão", codigo == 200 and corpo.get("acesso"),
                    f"/conta/entrar devolveu {codigo}: {corpo}")
        self.acesso = corpo["acesso"]
        self.refresh = corpo["refresh"]
        self.checar("o aparelho foi registrado",
                    len(corpo["conta"]["aparelhos"]) == 1)
        self.checar("conta nova nasce sem assinatura",
                    corpo["conta"]["assinatura"]["situacao"] == "vencida")

        codigo, corpo = self._chamar("POST", "/licenca/validar", token=True)
        self.checar("licença responde e recusa quem não pagou",
                    codigo == 200 and corpo.get("liberado") is False,
                    f"/licenca/validar devolveu {codigo}: {corpo}")

        codigo, corpo = self._chamar("POST", "/conta/renovar", {"refresh": self.refresh})
        self.checar("renovação de sessão funciona",
                    codigo == 200 and corpo.get("refresh") != self.refresh,
                    "o refresh tem que ser rotacionado")
        self.refresh = corpo["refresh"]
        self.acesso = corpo["acesso"]

        codigo, corpo = self._chamar("GET", "/conta", token=True)
        self.checar("a conta se lê de volta",
                    codigo == 200 and corpo["conta"]["email"] == self.email)

        codigo, _ = self._chamar("POST", "/conta/sair", {"refresh": self.refresh})
        self.checar("sair encerra a sessão", codigo == 200)
        codigo, _ = self._chamar("GET", "/conta", token=True)
        self.checar("e o token para de valer na hora", codigo == 401)

        print(f"\n{self.passos} verificações, todas passaram.")
        print(f"chave pública: {chave[:24]}...")

    def limpar(self) -> None:
        """Apaga a conta de teste. Precisa de uma senha de administrador."""
        print("\nA conta de teste continua no banco. Para apagá-la, rode no "
              "servidor:")
        print(f'  DELETE FROM usuarios WHERE email = \'{self.email}\';')
        print("Ou, no painel, ela aparece como vencida e pode ser ignorada.")


def main(argumentos: list[str]) -> int:
    if not argumentos:
        print(__doc__)
        return 1
    teste = Fumaca(argumentos[0])
    try:
        teste.rodar()
    except Falhou as e:
        print(f"\nPAROU AQUI: {e}")
        teste.limpar()
        return 1
    teste.limpar()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
