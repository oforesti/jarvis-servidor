"""Avisa por e-mail quando um pedido chega.

O servidor roda no PC de casa, que fica ligado so a noite. Entao o pedido
precisa te alcancar por fora dele — e o e-mail e o caminho que voce ja olha.

Manda numa thread e engole qualquer erro: um servidor de e-mail fora do ar nao
pode fazer o pedido de um cliente falhar. Se o aviso nao sair, o pedido
continua la no painel, que e a fonte da verdade.
"""

from __future__ import annotations

import logging
import os
import smtplib
import threading
from email.message import EmailMessage

from . import planos
from .config import config

log = logging.getLogger("servidor.aviso")


def _conta() -> tuple[str, str, str]:
    endereco = (os.getenv("JARVIS_LICENCA_SMTP_EMAIL") or "").strip()
    senha = (os.getenv("JARVIS_LICENCA_SMTP_SENHA") or "").strip()
    servidor = (os.getenv("JARVIS_LICENCA_SMTP") or "smtp.gmail.com").strip()
    return endereco, senha, servidor


def ligado() -> bool:
    endereco, senha, _ = _conta()
    return bool(endereco and senha and _destino())


def _destino() -> str:
    return ((os.getenv("JARVIS_LICENCA_AVISAR") or config.email_contato or "").strip())


def _enviar(assunto: str, corpo: str) -> None:
    endereco, senha, servidor = _conta()
    destino = _destino()
    if not (endereco and senha and destino):
        return
    try:
        msg = EmailMessage()
        msg["Subject"] = assunto
        msg["From"] = endereco
        msg["To"] = destino
        msg.set_content(corpo)
        with smtplib.SMTP(servidor, 587, timeout=20) as smtp:
            smtp.starttls()
            smtp.login(endereco, senha)
            smtp.send_message(msg)
        log.info("aviso de pedido enviado para %s", destino)
    except Exception as e:  # noqa: BLE001 — aviso nunca derruba o pedido
        log.warning("nao consegui avisar por e-mail: %s", e)


def avisar(assunto: str, corpo: str) -> None:
    """Numa thread na sua máquina; direto, em serverless.

    A função do Vercel é congelada assim que responde, e a thread morreria
    com o aviso pela metade. Lá o custo é um segundo a mais na resposta do
    pedido — barato, comparado a não ficar sabendo que alguém quer comprar.
    """
    if not ligado():
        return
    if config.sem_disco():
        _enviar(assunto, corpo)
        return
    threading.Thread(target=_enviar, args=(assunto, corpo), daemon=True,
                     name="jarvis-aviso-email").start()


def pedido_de_teste(pedido: dict, tem_conta: bool, alterado: bool = False) -> None:
    """O e-mail do teste grátis: sem valor a cobrar, com o prazo em destaque."""
    equipamentos = planos.equipamentos_do_pedido(planos.TESTE, pedido.get("aparelhos") or 0)
    quem = pedido.get("nome") or pedido["email"]
    linhas = [
        (f"{quem} ALTEROU o pedido de teste. Vale este, não o anterior." if alterado
         else f"{quem} quer TESTAR o Jarvis de graça por {planos.DIAS_TESTE} dias."),
        "",
        f"E-mail:        {pedido['email']}",
        f"WhatsApp:      {pedido.get('telefone') or '-'}",
        f"Pedido:        TESTE GRATIS de {planos.DIAS_TESTE} dias (nada a cobrar)",
        f"Equipamentos:  {planos.equipamentos_txt(equipamentos)} para liberar",
        "",
    ]
    if pedido.get("observacao"):
        linhas += ["Recado:", pedido["observacao"], ""]
    if not tem_conta:
        linhas += ["Atencao: essa pessoa ainda NAO criou a conta no Jarvis.",
                   "Sem conta nao da para liberar — avise ela para se cadastrar.", ""]
    linhas += [f"Para liberar, abra o painel na aba Pedidos e clique em "
               f"Liberar {planos.DIAS_TESTE} dias gratis.",
               f"Depois de {planos.DIAS_TESTE} dias o Jarvis para de abrir sozinho, "
               "ate um plano pago ser ativado."]
    avisar(f"Jarvis: {'teste alterado' if alterado else 'pedido de TESTE GRATIS'} de {quem} — "
           f"{planos.DIAS_TESTE} dias, {planos.equipamentos_txt(equipamentos)}",
           "\n".join(linhas))


def pedido_novo(pedido: dict, tem_conta: bool, alterado: bool = False) -> None:
    plano = pedido.get("plano") or planos.PADRAO
    if plano == planos.TESTE:
        pedido_de_teste(pedido, tem_conta, alterado)
        return
    equipamentos = planos.equipamentos_do_pedido(plano, pedido.get("aparelhos") or 0)
    quem = pedido.get("nome") or pedido["email"]
    linhas = [
        (f"{quem} ALTEROU o pedido. Vale este, não o anterior." if alterado
         else f"{quem} quer assinar o Jarvis."),
        "",
        f"E-mail:        {pedido['email']}",
        f"WhatsApp:      {pedido.get('telefone') or '-'}",
        f"Plano:         {planos.nome(plano)} ({planos.pessoas_txt(plano)})",
        f"Equipamentos:  {planos.equipamentos_txt(equipamentos)}"
        + ("" if equipamentos is None else " para liberar"),
        f"Valor:         {planos.moeda(planos.preco(plano))} por mes",
        "",
    ]
    if pedido.get("observacao"):
        linhas += ["Recado:", pedido["observacao"], ""]
    if not tem_conta:
        linhas += ["Atencao: essa pessoa ainda NAO criou a conta no Jarvis.",
                   "Sem conta nao da para liberar — avise ela para se cadastrar.", ""]
    linhas += ["Para liberar, abra o painel na aba Pedidos e clique em Liberar 30 dias.",
               f"Isso ja ativa o plano {planos.nome(plano)} com "
               f"{planos.equipamentos_txt(equipamentos)}."]
    avisar(f"Jarvis: {'pedido alterado' if alterado else 'pedido'} de {quem} — "
           f"{planos.nome(plano)}, {planos.equipamentos_txt(equipamentos)}, "
           f"{planos.moeda(planos.preco(plano))}/mes",
           "\n".join(linhas))
