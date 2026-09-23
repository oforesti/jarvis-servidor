"""Painel administrativo — onde você libera quem pagou.

Duas decisões que moldam esta tela:

1. **A ação mais comum acontece na lista.** O caso de todo dia é "o Pix da
   fulana caiu, libera ela". Isso é um clique na linha dela, sem abrir página
   nenhuma — e sem recarregar, porque recarregar num celular com 4G ruim é o
   que fazia o painel anterior parecer travado.
2. **Sem build.** HTML e CSS servidos direto, e o pouco de JavaScript que
   existe é para não recarregar. Uma tela que só você usa, do meio da rua,
   precisa abrir sempre — e página que depende de compilação um dia não abre.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape
from urllib.parse import parse_qs

import jwt
from fastapi import APIRouter, Cookie, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from .. import acessos, assinaturas, banco, contas, pedidos
from ..config import config

rotas = APIRouter(prefix="/admin", tags=["admin"])
COOKIE = "jarvis_admin"

MENSALIDADE = 39.99
POR_APARELHO = 10.00


# ------------------------------------------------------------------ sessão
def _criar_cookie(usuario_id: int) -> str:
    agora = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": str(usuario_id), "adm": True,
         "exp": int((agora + timedelta(hours=12)).timestamp())},
        config.segredo_jwt, algorithm="HS256")


def _admin_logado(cookie: str | None) -> dict | None:
    if not cookie:
        return None
    try:
        dados = jwt.decode(cookie, config.segredo_jwt, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    usuario = banco.um("SELECT id, email, admin FROM usuarios WHERE id = ?",
                       (int(dados.get("sub", 0)),))
    return dict(usuario) if usuario and usuario["admin"] else None


async def _formulario(request: Request) -> dict:
    """Lê um POST de formulário sem depender do python-multipart."""
    bruto = (await request.body()).decode("utf-8", "replace")
    return {k: v[0] for k, v in parse_qs(bruto).items()}


# ------------------------------------------------------------------ visual
ESTILO = """
:root {
  --acento:#3fe0ff; --acento-08:rgba(63,224,255,.07); --acento-18:rgba(63,224,255,.18);
  --borda:rgba(63,224,255,.14); --texto:#d6faff; --fraco:rgba(214,250,255,.55);
  --tenue:rgba(214,250,255,.28); --ok:#4dffa6; --alerta:#ffb23f; --perigo:#ff5f6d;
  color-scheme:dark;
}
*{box-sizing:border-box;}
body{margin:0;padding:0 0 60px;background:radial-gradient(circle at 50% -20%,#0b1e2a,#03070a 60%);
 color:var(--texto);font:15px/1.5 'Segoe UI',system-ui,sans-serif;min-height:100vh;}
a{color:var(--acento);text-decoration:none;}
.topo{position:sticky;top:0;z-index:5;display:flex;align-items:center;gap:14px;flex-wrap:wrap;
 padding:14px 22px;background:rgba(3,7,10,.85);backdrop-filter:blur(8px);
 border-bottom:1px solid var(--borda);}
.marca{font-weight:700;letter-spacing:5px;color:var(--acento);font-size:14px;}
.topo .espaco{flex:1;}
.topo a{font-size:13.5px;color:var(--fraco);}
.topo a:hover,.topo a.ativo{color:var(--acento);}
.folha{max-width:1000px;margin:0 auto;padding:22px;}
h1{font-size:19px;font-weight:600;margin:0 0 16px;}
h2{font-size:12px;letter-spacing:2px;text-transform:uppercase;color:var(--acento);
 margin:0 0 12px;font-weight:600;}

.numeros{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:22px;}
.numero{border:1px solid var(--borda);background:var(--acento-08);border-radius:12px;padding:14px 16px;}
.numero b{display:block;font-size:26px;font-weight:600;line-height:1.1;}
.numero span{display:block;font-size:11.5px;letter-spacing:1.4px;text-transform:uppercase;
 color:var(--tenue);margin-top:4px;}
.numero.bom b{color:var(--ok);} .numero.aviso b{color:var(--alerta);} .numero.ruim b{color:var(--perigo);}

.painel{border:1px solid var(--borda);background:rgba(8,18,26,.55);border-radius:14px;
 padding:18px;margin-bottom:16px;}
.busca{display:flex;gap:8px;margin-bottom:14px;}
input,select{background:#0a1720;border:1px solid rgba(63,224,255,.2);color:var(--texto);
 border-radius:9px;padding:11px 13px;font-size:14.5px;font-family:inherit;width:100%;}
input:focus{outline:none;border-color:rgba(63,224,255,.5);}

.linha{display:flex;align-items:center;gap:12px;padding:13px 14px;border-radius:11px;
 border:1px solid var(--borda);background:var(--acento-08);margin-bottom:8px;flex-wrap:wrap;}
.linha:hover{border-color:rgba(63,224,255,.3);}
.quem{flex:1 1 220px;min-width:0;}
.quem b{display:block;font-size:14.5px;font-weight:600;overflow:hidden;text-overflow:ellipsis;
 white-space:nowrap;}
.quem span{font-size:12.5px;color:var(--fraco);}
.pilula{font-size:11px;letter-spacing:1.3px;text-transform:uppercase;padding:3px 10px;
 border-radius:20px;font-weight:600;flex:0 0 auto;}
.ativa{background:rgba(77,255,166,.14);color:var(--ok);}
.vencida{background:rgba(255,178,63,.14);color:var(--alerta);}
.bloqueada{background:rgba(255,95,109,.14);color:var(--perigo);}
.acoes{display:flex;gap:6px;flex:0 0 auto;flex-wrap:wrap;}
button{background:var(--acento-18);border:1px solid rgba(63,224,255,.4);color:var(--texto);
 border-radius:8px;padding:8px 13px;font-size:13.5px;font-family:inherit;cursor:pointer;
 white-space:nowrap;}
button:hover:not(:disabled){background:rgba(63,224,255,.3);}
button:disabled{opacity:.45;cursor:default;}
button.fantasma{background:none;border-color:var(--borda);color:var(--fraco);}
button.perigo{background:none;border-color:rgba(255,95,109,.4);color:#ff9aa2;}
button.grande{padding:11px 18px;font-size:14.5px;}

table{width:100%;border-collapse:collapse;font-size:13.5px;}
th,td{text-align:left;padding:9px 10px;border-bottom:1px solid rgba(63,224,255,.1);}
th{color:var(--tenue);font-weight:500;font-size:11px;text-transform:uppercase;letter-spacing:1.3px;}
.vazio{color:var(--tenue);font-style:italic;padding:18px;text-align:center;}

#aviso{position:fixed;left:50%;bottom:26px;transform:translate(-50%,90px);z-index:20;
 background:#0b1e2a;border:1px solid var(--borda);border-radius:10px;padding:12px 20px;
 font-size:14px;box-shadow:0 10px 40px rgba(0,0,0,.5);transition:transform .25s ease;}
#aviso.aparece{transform:translate(-50%,0);}
#aviso.bom{border-color:rgba(77,255,166,.45);color:#a8ffd4;}
#aviso.ruim{border-color:rgba(255,95,109,.45);color:#ffb3b8;}

.selo-conta[hidden]{display:none;}
.selo-conta{display:inline-block;min-width:18px;padding:1px 6px;border-radius:10px;
 background:var(--alerta);color:#2a1a00;font-size:11px;font-weight:700;text-align:center;}
.pedido{border:1px solid var(--borda);background:var(--acento-08);border-radius:11px;
 padding:14px 16px;margin-bottom:10px;}
.pedido.novo{border-color:rgba(255,178,63,.4);}
.pedido b{font-size:15px;}
.pedido .detalhe{color:var(--fraco);font-size:13px;margin:4px 0 12px;}
.pedido .obs{border-left:2px solid var(--borda);padding-left:10px;margin:8px 0 12px;
 color:var(--fraco);font-size:13.5px;font-style:italic;}
.conta-acesso{border:1px solid var(--borda);background:var(--acento-08);border-radius:12px;
 padding:16px;margin-bottom:12px;}
.conta-acesso.atencao{border-color:rgba(255,178,63,.45);}
.conta-acesso .cabeca{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:4px;}
.conta-acesso .cabeca b{font-size:15px;}
.contagem{font-family:'Segoe UI',system-ui,sans-serif;font-size:12.5px;color:var(--fraco);
 margin-bottom:12px;}
.contagem b{color:var(--texto);}
.aparelho-ips{border-top:1px solid rgba(63,224,255,.1);padding-top:10px;margin-top:10px;}
.aparelho-ips h4{margin:0 0 6px;font-size:13px;font-weight:600;color:var(--texto);}
.ip{display:inline-flex;align-items:center;gap:6px;margin:0 6px 6px 0;padding:4px 8px 4px 10px;
 border-radius:8px;border:1px solid var(--borda);background:rgba(3,7,10,.5);
 font-family:ui-monospace,Consolas,monospace;font-size:12.5px;}
.ip small{color:var(--tenue);font-family:'Segoe UI',system-ui,sans-serif;}
.ip button{padding:2px 7px;font-size:11px;border-radius:6px;}
.ip.barrado{border-color:rgba(255,95,109,.45);color:#ff9aa2;}
.explica{border:1px dashed var(--borda);border-radius:11px;padding:14px 16px;margin-bottom:16px;
 color:var(--fraco);font-size:13.5px;line-height:1.6;}
.explica b{color:var(--texto);}
.entrada{max-width:380px;margin:12vh auto;}
.entrada input{margin-bottom:10px;}
.entrada button{width:100%;}
@media (max-width:620px){
  .folha{padding:14px;} .linha{gap:8px;} .acoes{width:100%;}
  .acoes button{flex:1;}
}
"""

SCRIPT = """
function aviso(texto, bom) {
  var el = document.getElementById('aviso');
  el.textContent = texto;
  el.className = 'aparece ' + (bom ? 'bom' : 'ruim');
  clearTimeout(window._t);
  window._t = setTimeout(function () { el.className = ''; }, 3200);
}

/* A acao acontece na linha e a linha se atualiza sozinha: sem recarregar a
   pagina, que e o que fazia o painel parecer travado no celular. */
function acao(id, qual, botao) {
  if (botao) botao.disabled = true;
  fetch('/admin/acao', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ usuario: id, acao: qual })
  }).then(function (r) { return r.json(); }).then(function (d) {
    if (botao) botao.disabled = false;
    if (!d.ok) { aviso(d.erro || 'nao consegui', false); return; }
    aviso(d.msg, true);
    var linha = document.getElementById('linha-' + id);
    if (linha && d.html) linha.outerHTML = d.html;
    if (d.numeros) atualizarNumeros(d.numeros);
  }).catch(function (e) {
    if (botao) botao.disabled = false;
    aviso('falhou: ' + e.message, false);
  });
}

/* o selo da barra e o cartao do topo mostram o mesmo numero em dois lugares */
function atualizarPedidos(quantos) {
  var cartao = document.getElementById('n-pedidos');
  if (cartao) cartao.textContent = quantos;
  var selo = document.getElementById('selo-pedidos');
  if (selo) { selo.textContent = quantos; selo.hidden = !quantos; }
}

function atualizarNumeros(n) {
  if (n.pedidos !== undefined) atualizarPedidos(n.pedidos);
  Object.keys(n).forEach(function (k) {
    var el = document.getElementById('n-' + k);
    if (el) el.textContent = n[k];
  });
}

function removerAparelho(usuario, aparelho, botao) {
  botao.disabled = true;
  fetch('/admin/acao', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ usuario: usuario, acao: 'remover_aparelho', aparelho: aparelho })
  }).then(function (r) { return r.json(); }).then(function (d) {
    if (!d.ok) { botao.disabled = false; aviso(d.erro || 'nao consegui', false); return; }
    aviso('aparelho desconectado', true);
    var linha = botao.closest('tr');
    if (linha) linha.remove();
  });
}

function pedido(id, qual, botao) {
  botao.disabled = true;
  fetch('/admin/pedido', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pedido: id, acao: qual })
  }).then(function (r) { return r.json(); }).then(function (d) {
    botao.disabled = false;
    if (!d.ok) { aviso(d.erro || 'nao consegui', false); return; }
    aviso(d.msg, true);
    var cartao = document.getElementById('pedido-' + id);
    if (cartao) { cartao.outerHTML = d.html || ''; }
    if (d.numeros) atualizarPedidos(d.numeros.pedidos);
  }).catch(function (e) { botao.disabled = false; aviso('falhou: ' + e.message, false); });
}

function ipAcao(ip, qual, botao) {
  botao.disabled = true;
  fetch('/admin/ip', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ip: ip, acao: qual })
  }).then(function (r) { return r.json(); }).then(function (d) {
    botao.disabled = false;
    if (!d.ok) { aviso(d.erro || 'nao consegui', false); return; }
    aviso(d.msg, true);
    document.querySelectorAll('[data-ip="' + ip + '"]').forEach(function (caixa) {
      caixa.classList.toggle('barrado', qual === 'bloquear');
      var b = caixa.querySelector('button');
      b.textContent = qual === 'bloquear' ? 'liberar' : 'bloquear';
      b.setAttribute('onclick', "ipAcao('" + ip + "','" +
        (qual === 'bloquear' ? 'liberar' : 'bloquear') + "',this)");
    });
  }).catch(function (e) { botao.disabled = false; aviso('falhou: ' + e.message, false); });
}

function filtrar(termo) {
  termo = termo.toLowerCase();
  document.querySelectorAll('[data-email]').forEach(function (l) {
    l.style.display = l.dataset.email.indexOf(termo) >= 0 ? '' : 'none';
  });
}
"""


def _selo_pedidos() -> str:
    """O numero ao lado de "pedidos" e o que faz voce nao esquecer deles.

    Sai sempre no HTML, escondido quando e zero, para o JavaScript conseguir
    atualiza-lo depois de atender um pedido sem recarregar a pagina.
    """
    quantos = pedidos.quantos_novos()
    oculto = "" if quantos else " hidden"
    return f' <span class="selo-conta" id="selo-pedidos"{oculto}>{quantos}</span>'


def _pagina(titulo: str, corpo: str, quem: str = "", aba: str = "") -> HTMLResponse:
    topo = ""
    if quem:
        topo = (
            '<div class="topo"><span class="marca">JARVIS</span>'
            f'<a href="/admin" class="{"ativo" if aba == "contas" else ""}">contas</a>'
            f'<a href="/admin/pedidos" class="{"ativo" if aba == "pedidos" else ""}">pedidos{_selo_pedidos()}</a>'
            f'<a href="/admin/acessos" class="{"ativo" if aba == "acessos" else ""}">acessos</a>'
            f'<a href="/admin/recusas" class="{"ativo" if aba == "recusas" else ""}">recusas</a>'
            f'<span class="espaco"></span><span style="font-size:13px;color:var(--tenue)">{escape(quem)}</span>'
            '<a href="/admin/sair">sair</a></div>')
    return HTMLResponse(
        "<!doctype html><html lang='pt-br'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{escape(titulo)} · Jarvis</title><style>{ESTILO}</style></head><body>"
        f"{topo}<div class='folha'>{corpo}</div><div id='aviso'></div>"
        f"<script>{SCRIPT}</script></body></html>")


# ------------------------------------------------------------------ dados
def _numeros() -> dict:
    linhas = banco.consultar(
        "SELECT u.id, u.bloqueado, a.aparelhos_pagos FROM usuarios u "
        "LEFT JOIN assinaturas a ON a.usuario_id = u.id")
    ativas = vencidas = bloqueadas = extras = 0
    for l in linhas:
        estado = contas.estado_da_assinatura(l["id"])
        if estado["situacao"] == "ativa":
            ativas += 1
            extras += l["aparelhos_pagos"] or 0
        elif estado["situacao"] == "bloqueada" or l["bloqueado"]:
            bloqueadas += 1
        else:
            vencidas += 1

    aparelhos = banco.um("SELECT COUNT(*) AS n FROM aparelhos")["n"]
    novos = pedidos.quantos_novos()
    desde = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
    recusas = banco.um("SELECT COUNT(*) AS n FROM recusas WHERE quando > ?", (desde,))["n"]
    mensal = ativas * MENSALIDADE + extras * POR_APARELHO
    return {"ativas": ativas, "vencidas": vencidas, "bloqueadas": bloqueadas,
            "aparelhos": aparelhos, "recusas": recusas, "pedidos": novos,
            "receita": f"R$ {mensal:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")}


def _linha(usuario_id: int) -> str:
    """Uma linha da lista, com a ação principal à mão.

    Devolvida também pela rota de ação, para o JavaScript trocar só ela.
    """
    u = banco.um("SELECT id, email, bloqueado FROM usuarios WHERE id = ?", (usuario_id,))
    if u is None:
        return ""
    estado = contas.estado_da_assinatura(usuario_id)
    validade = banco.para_data(estado["validade"])
    aparelhos = banco.um("SELECT COUNT(*) AS n FROM aparelhos WHERE usuario_id = ?",
                         (usuario_id,))["n"]

    if estado["situacao"] == "ativa" and validade:
        dias = (validade - datetime.now(timezone.utc)).days
        quando = f"vence em {dias} dia{'s' if dias != 1 else ''}" if dias <= 7 else \
                 f"até {validade.strftime('%d/%m/%Y')}"
    elif validade:
        quando = f"venceu em {validade.strftime('%d/%m/%Y')}"
    else:
        quando = "nunca ativada"

    rotulo = "bloqueada" if u["bloqueado"] else estado["situacao"]
    principal = (f'<button onclick="acao({usuario_id},\'ativar30\',this)">+ 30 dias</button>'
                 if not u["bloqueado"] else
                 f'<button onclick="acao({usuario_id},\'desbloquear\',this)">desbloquear</button>')

    return (
        f'<div class="linha" id="linha-{usuario_id}" data-email="{escape(u["email"].lower())}">'
        f'  <span class="quem"><b>{escape(u["email"])}</b>'
        f'    <span>{quando} · {aparelhos} de {estado["limite"]} aparelhos</span></span>'
        f'  <span class="pilula {rotulo}">{rotulo}</span>'
        f'  <span class="acoes">{principal}'
        f'    <button class="fantasma" onclick="acao({usuario_id},\'mais_aparelho\',this)">+ aparelho</button>'
        f'    <a href="/admin/usuario/{usuario_id}"><button class="fantasma">abrir</button></a>'
        f'  </span></div>')


# ------------------------------------------------------------------- telas
@rotas.get("", response_class=HTMLResponse)
def inicio(jarvis_admin: str | None = Cookie(default=None)):
    admin = _admin_logado(jarvis_admin)
    if admin is None:
        return _pagina("Painel", """
          <div class="painel entrada">
            <h1 style="text-align:center">Painel do Jarvis</h1>
            <form method="post" action="/admin/entrar">
              <input name="email" type="email" placeholder="seu e-mail" required autofocus>
              <input name="senha" type="password" placeholder="sua senha" required>
              <button class="grande" type="submit">Entrar</button>
            </form>
          </div>""")

    n = _numeros()
    ids = [l["id"] for l in banco.consultar("SELECT id FROM usuarios ORDER BY id DESC LIMIT 300")]
    linhas = "".join(_linha(i) for i in ids) or '<div class="vazio">nenhuma conta ainda</div>'

    corpo = f"""
      <div class="numeros">
        <div class="numero bom"><b id="n-ativas">{n['ativas']}</b><span>pagando</span></div>
        <div class="numero aviso"><b id="n-vencidas">{n['vencidas']}</b><span>vencidas</span></div>
        <div class="numero ruim"><b id="n-bloqueadas">{n['bloqueadas']}</b><span>bloqueadas</span></div>
        <div class="numero"><b id="n-aparelhos">{n['aparelhos']}</b><span>aparelhos</span></div>
        <div class="numero{' aviso' if n['pedidos'] else ''}"><b id="n-pedidos">{n['pedidos']}</b>
          <span>{'pedidos novos' if n['pedidos'] != 1 else 'pedido novo'}</span></div>
        <div class="numero"><b id="n-receita" style="font-size:20px">{n['receita']}</b><span>por mês</span></div>
      </div>
      <div class="painel">
        <div class="busca">
          <input id="filtro" placeholder="filtrar por e-mail" oninput="filtrar(this.value)" autofocus>
        </div>
        {linhas}
      </div>
      <p style="color:var(--tenue);font-size:12.5px;text-align:center">
        O Pix caiu? Ache o e-mail e clique em <b>+ 30 dias</b>. Quem paga adiantado soma os dias.
      </p>"""
    return _pagina("Contas", corpo, admin["email"], "contas")


@rotas.post("/entrar")
async def entrar(request: Request):
    dados = await _formulario(request)
    try:
        usuario = contas.autenticar(dados.get("email", ""), dados.get("senha", ""))
    except contas.ErroConta as e:
        return _pagina("Painel", f"""
          <div class="painel entrada">
            <h1 style="text-align:center">Painel do Jarvis</h1>
            <p style="color:#ffb3b8">{escape(e.mensagem)}</p>
            <a href="/admin"><button class="grande">tentar de novo</button></a>
          </div>""")
    if not usuario["admin"]:
        banco.anotar_recusa("admin_negado", email=usuario["email"])
        return _pagina("Painel", '<div class="painel entrada">'
                                 '<p>esta conta não é administradora</p></div>')

    resposta = RedirectResponse("/admin", status_code=303)
    resposta.set_cookie(COOKIE, _criar_cookie(usuario["id"]), httponly=True,
                        samesite="lax", max_age=12 * 3600)
    return resposta


@rotas.get("/sair")
def sair():
    resposta = RedirectResponse("/admin", status_code=303)
    resposta.delete_cookie(COOKIE)
    return resposta


@rotas.post("/acao")
async def acao(request: Request, jarvis_admin: str | None = Cookie(default=None)):
    """Uma ação, uma linha atualizada. Sem recarregar a página."""
    admin = _admin_logado(jarvis_admin)
    if admin is None:
        return JSONResponse({"ok": False, "erro": "sua sessão expirou — entre de novo"}, 401)

    try:
        dados = await request.json()
    except Exception:  # noqa: BLE001
        dados = await _formulario(request)

    usuario_id = int(dados.get("usuario") or 0)
    qual = str(dados.get("acao") or "")
    if not banco.um("SELECT id FROM usuarios WHERE id = ?", (usuario_id,)):
        return JSONResponse({"ok": False, "erro": "essa conta não existe"}, 404)

    estado = contas.estado_da_assinatura(usuario_id)
    mensagens = {
        "ativar30": "liberada por 30 dias",
        "ativar365": "liberada por 1 ano",
        "vencer": "assinatura vencida",
        "bloquear": "conta bloqueada",
        "desbloquear": "conta desbloqueada",
        "mais_aparelho": "mais um aparelho liberado",
        "menos_aparelho": "um aparelho a menos",
    }
    if qual == "ativar30":
        assinaturas.ativar(usuario_id, 30)
    elif qual == "ativar365":
        assinaturas.ativar(usuario_id, 365)
    elif qual == "vencer":
        assinaturas.vencer(usuario_id, motivo=f"vencida no painel por {admin['email']}")
    elif qual == "bloquear":
        assinaturas.bloquear(usuario_id, motivo=f"bloqueada no painel por {admin['email']}")
    elif qual == "desbloquear":
        assinaturas.desbloquear(usuario_id)
    elif qual == "mais_aparelho":
        assinaturas.definir_aparelhos_pagos(usuario_id, estado["aparelhos_pagos"] + 1)
    elif qual == "menos_aparelho":
        if estado["aparelhos_pagos"] <= 0:
            return JSONResponse({"ok": False, "erro": "já está no plano base"}, 400)
        assinaturas.definir_aparelhos_pagos(usuario_id, estado["aparelhos_pagos"] - 1)
    elif qual == "remover_aparelho":
        contas.remover_aparelho(usuario_id, int(dados.get("aparelho") or 0))
        mensagens[qual] = "aparelho desconectado"
    else:
        return JSONResponse({"ok": False, "erro": f"ação desconhecida: {qual}"}, 400)

    return JSONResponse({"ok": True, "msg": mensagens.get(qual, "feito"),
                         "html": _linha(usuario_id), "numeros": _numeros()})


@rotas.get("/usuario/{usuario_id}", response_class=HTMLResponse)
def usuario(usuario_id: int, jarvis_admin: str | None = Cookie(default=None)):
    admin = _admin_logado(jarvis_admin)
    if admin is None:
        return RedirectResponse("/admin", status_code=303)
    alvo = banco.um("SELECT * FROM usuarios WHERE id = ?", (usuario_id,))
    if alvo is None:
        return _pagina("Conta", '<div class="painel vazio">essa conta não existe</div>',
                       admin["email"])

    estado = contas.estado_da_assinatura(usuario_id)
    aparelhos = contas.aparelhos_do_usuario(usuario_id)
    criada = banco.para_data(alvo["criado_em"])

    def linha_aparelho(a: dict) -> str:
        quando = escape(str(a["ultimo_acesso"])[:16].replace("T", " "))
        botao = (f'<button class="perigo" '
                 f'onclick="removerAparelho({usuario_id},{int(a["id"])},this)">remover</button>')
        return (f'<tr><td>{escape(a["apelido"] or "—")}</td>'
                f'<td>{escape(a["plataforma"] or "—")}</td><td>{quando}</td>'
                f'<td>{botao}</td></tr>')

    corpo = f"""
      <h1>{escape(alvo['email'])}</h1>
      <div class="painel">
        {_linha(usuario_id)}
        <p style="color:var(--tenue);font-size:12.5px;margin:10px 0 0">
          conta criada em {criada.strftime('%d/%m/%Y') if criada else '—'} ·
          {estado['aparelhos_pagos']} aparelho(s) adicional(is) pago(s)
        </p>
      </div>
      <div class="painel">
        <h2>Assinatura</h2>
        <div class="acoes">
          <button onclick="acao({usuario_id},'ativar30',this)">+ 30 dias</button>
          <button onclick="acao({usuario_id},'ativar365',this)">+ 1 ano</button>
          <button class="fantasma" onclick="acao({usuario_id},'mais_aparelho',this)">+ aparelho pago</button>
          <button class="fantasma" onclick="acao({usuario_id},'menos_aparelho',this)">− aparelho pago</button>
          <button class="perigo" onclick="acao({usuario_id},'vencer',this)">vencer agora</button>
          <button class="perigo" onclick="acao({usuario_id},'{'desbloquear' if alvo['bloqueado'] else 'bloquear'}',this)">
            {'desbloquear conta' if alvo['bloqueado'] else 'bloquear conta'}</button>
        </div>
      </div>
      <div class="painel">
        <h2>Aparelhos ligados</h2>
        <table><tr><th>apelido</th><th>plataforma</th><th>último acesso</th><th></th></tr>
        {''.join(linha_aparelho(a) for a in aparelhos)
         or '<tr><td colspan="4" class="vazio">nenhum aparelho ligado</td></tr>'}
        </table>
      </div>"""
    return _pagina("Conta", corpo, admin["email"], "contas")


def _cartao_pedido(pedido_id: int) -> str:
    linha = banco.um("SELECT * FROM pedidos WHERE id = ?", (pedido_id,))
    if linha is None:
        return ""
    p = dict(linha)
    quando = escape(str(p["quando"])[:16].replace("T", " "))
    tem_conta = banco.um("SELECT id FROM usuarios WHERE email = ?", (p["email"],)) is not None

    plano = "Assinatura" if p["plano"] == "base" else escape(p["plano"])
    extras = f" + {p['aparelhos']} aparelho(s)" if p["aparelhos"] else ""
    valor = MENSALIDADE + p["aparelhos"] * POR_APARELHO
    valor_txt = f"R$ {valor:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")

    if p["situacao"] == "novo":
        aviso_conta = ("" if tem_conta else
                       '<div class="obs">Ainda não criou a conta no Jarvis — '
                       'liberar só funciona depois que ela se cadastrar.</div>')
        acoes = (f"<button onclick=\"pedido({pedido_id},'atender',this)\">"
                 f"Liberar 30 dias</button>"
                 f"<button class='fantasma' onclick=\"pedido({pedido_id},'recusar',this)\">"
                 f"Arquivar</button>")
    else:
        aviso_conta = ""
        acoes = (f"<button class='fantasma' onclick=\"pedido({pedido_id},'reabrir',this)\">"
                 f"Reabrir</button>")

    observacao = (f'<div class="obs">{escape(p["observacao"])}</div>'
                  if p["observacao"] else "")
    selo = {"novo": "vencida", "atendido": "ativa", "recusado": "bloqueada"}[p["situacao"]]
    rotulo = {"novo": "novo", "atendido": "atendido", "recusado": "arquivado"}[p["situacao"]]

    return (
        f'<div class="pedido {"novo" if p["situacao"] == "novo" else ""}" id="pedido-{pedido_id}">'
        f'  <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">'
        f'    <b>{escape(p["nome"] or p["email"])}</b>'
        f'    <span class="pilula {selo}">{rotulo}</span></div>'
        f'  <div class="detalhe">{escape(p["email"])}'
        f'{" · " + escape(p["telefone"]) if p["telefone"] else ""}'
        f' · {plano}{extras} · {valor_txt}/mês · {quando}</div>'
        f'{observacao}'
        f'{aviso_conta}'
        f'  <div class="acoes">{acoes}</div></div>')


@rotas.get("/pedidos", response_class=HTMLResponse)
def lista_pedidos(jarvis_admin: str | None = Cookie(default=None)):
    admin = _admin_logado(jarvis_admin)
    if admin is None:
        return RedirectResponse("/admin", status_code=303)

    todos = pedidos.listar("todos", 150)
    novos = [p for p in todos if p["situacao"] == "novo"]
    antigos = [p for p in todos if p["situacao"] != "novo"]

    corpo = ['<h1>Pedidos de compra</h1>',
             '<div class="painel">',
             '<p style="color:var(--tenue);font-size:13px;margin:0 0 14px">'
             'Vieram do site. Confirme o pagamento e clique em <b>Liberar 30 dias</b> — '
             'isso ativa a conta e fecha o pedido de uma vez.</p>']
    corpo += [_cartao_pedido(p["id"]) for p in novos] or [
        '<div class="vazio">nenhum pedido novo</div>']
    corpo.append("</div>")
    if antigos:
        corpo.append('<div class="painel"><h2>Já resolvidos</h2>')
        corpo += [_cartao_pedido(p["id"]) for p in antigos]
        corpo.append("</div>")
    return _pagina("Pedidos", "".join(corpo), admin["email"], "pedidos")


@rotas.post("/pedido")
async def acao_pedido(request: Request, jarvis_admin: str | None = Cookie(default=None)):
    admin = _admin_logado(jarvis_admin)
    if admin is None:
        return JSONResponse({"ok": False, "erro": "sua sessão expirou — entre de novo"}, 401)
    dados = await request.json()
    pedido_id = int(dados.get("pedido") or 0)
    qual = str(dados.get("acao") or "")

    try:
        if qual == "atender":
            resultado = pedidos.atender(pedido_id)
            msg = f"{resultado['email']} liberada por 30 dias"
        elif qual == "recusar":
            pedidos.marcar(pedido_id, "recusado")
            msg = "pedido arquivado"
        elif qual == "reabrir":
            pedidos.marcar(pedido_id, "novo")
            msg = "pedido reaberto"
        else:
            return JSONResponse({"ok": False, "erro": f"ação desconhecida: {qual}"}, 400)
    except contas.ErroConta as e:
        return JSONResponse({"ok": False, "erro": e.mensagem}, e.http)

    return JSONResponse({"ok": True, "msg": msg, "html": _cartao_pedido(pedido_id),
                         "numeros": _numeros()})


def _caixa_ip(ip: str, visto: str, vezes: int, barrados: set) -> str:
    esta = ip in barrados
    rotulo = "liberar" if esta else "bloquear"
    acao = "liberar" if esta else "bloquear"
    quando = escape(str(visto)[:16].replace("T", " "))
    return (f'<span class="ip{" barrado" if esta else ""}" data-ip="{escape(ip)}">'
            f'{escape(ip)} <small>{quando} · {vezes}x</small>'
            f'<button class="fantasma" onclick="ipAcao(\'{escape(ip)}\',\'{acao}\',this)">'
            f'{rotulo}</button></span>')


@rotas.get("/acessos", response_class=HTMLResponse)
def lista_acessos(jarvis_admin: str | None = Cookie(default=None)):
    admin = _admin_logado(jarvis_admin)
    if admin is None:
        return RedirectResponse("/admin", status_code=303)

    barrados = {b["ip"] for b in acessos.lista_bloqueados()}
    contas_ = acessos.por_conta(30)

    corpo = ['<h1>Acessos</h1>',
             '<div class="explica">'
             'De onde cada conta se conectou nos ultimos 30 dias. '
             '<b>Muitos IPs nao quer dizer pirataria:</b> o roteador de casa troca de '
             'IP sozinho, o celular muda a cada antena no 4G, e o Wi-Fi da escola e '
             'outro. Um cliente honesto aparece com tres ou quatro num dia. '
             'Quem realmente barra copia da pasta e o <b>limite de aparelhos</b>, que usa '
             'a impressao digital da maquina e nao o IP. '
             'Use esta tela para desconfiar, e prefira bloquear a conta ou desconectar '
             'o aparelho a bloquear o IP — bloquear IP tambem atinge quem divide a '
             'mesma internet.</div>']

    for c in contas_:
        selo = f'<span class="pilula {c["situacao"]}">{c["situacao"]}</span>'
        alerta = ('<span class="pilula vencida">muitos IPs</span>'
                  if c["ips_demais"] else "")
        blocos = []
        for aparelho in c["aparelhos"]:
            ips = c["por_aparelho"].get(aparelho["id"], [])
            caixas = "".join(_caixa_ip(i["ip"], i["ultimo"], i["vezes"], barrados)
                             for i in ips) or '<small style="color:var(--tenue)">sem acesso registrado ainda</small>'
            blocos.append(
                f'<div class="aparelho-ips"><h4>{escape(aparelho["apelido"] or "aparelho")}'
                f' <small style="color:var(--tenue);font-weight:400">'
                f'{escape(aparelho["plataforma"] or "")}</small></h4>{caixas}</div>')

        soltos = c["por_aparelho"].get(None, [])
        if soltos:
            caixas = "".join(_caixa_ip(i["ip"], i["ultimo"], i["vezes"], barrados)
                             for i in soltos)
            blocos.append(f'<div class="aparelho-ips"><h4>Sem aparelho identificado</h4>{caixas}</div>')

        corpo.append(
            f'<div class="conta-acesso{" atencao" if c["ips_demais"] else ""}">'
            f'  <div class="cabeca"><b>{escape(c["email"])}</b>{selo}{alerta}</div>'
            f'  <div class="contagem"><b>{len(c["aparelhos"])}</b> de <b>{c["limite"]}</b> '
            f'aparelhos liberados · <b>{c["quantos_ips"]}</b> IP(s) diferentes em 30 dias</div>'
            f'  {"".join(blocos)}</div>')

    if not contas_:
        corpo.append('<div class="painel vazio">ninguem se conectou ainda</div>')

    if barrados:
        corpo.append('<div class="painel"><h2>IPs bloqueados</h2>')
        for b in acessos.lista_bloqueados():
            corpo.append(
                f'<div class="linha"><span class="quem"><b>{escape(b["ip"])}</b>'
                f'<span>{escape(b["motivo"] or "sem motivo anotado")} · '
                f'{escape(str(b["quando"])[:16].replace("T", " "))}</span></span>'
                f'<span class="acoes"><button class="fantasma" '
                f'onclick="ipAcao(\'{escape(b["ip"])}\',\'liberar\',this)">liberar</button>'
                f'</span></div>')
        corpo.append("</div>")

    return _pagina("Acessos", "".join(corpo), admin["email"], "acessos")


@rotas.post("/ip")
async def acao_ip(request: Request, jarvis_admin: str | None = Cookie(default=None)):
    admin = _admin_logado(jarvis_admin)
    if admin is None:
        return JSONResponse({"ok": False, "erro": "sua sessão expirou — entre de novo"}, 401)
    dados = await request.json()
    ip = str(dados.get("ip") or "").strip()
    qual = str(dados.get("acao") or "")
    if not ip:
        return JSONResponse({"ok": False, "erro": "sem IP"}, 400)

    if qual == "bloquear":
        acessos.bloquear(ip, motivo=f"bloqueado no painel por {admin['email']}",
                         por=admin["email"])
        msg = f"{ip} bloqueado"
    elif qual == "liberar":
        acessos.liberar(ip)
        msg = f"{ip} liberado"
    else:
        return JSONResponse({"ok": False, "erro": f"ação desconhecida: {qual}"}, 400)
    return JSONResponse({"ok": True, "msg": msg})


@rotas.get("/recusas", response_class=HTMLResponse)
def recusas(jarvis_admin: str | None = Cookie(default=None)):
    admin = _admin_logado(jarvis_admin)
    if admin is None:
        return RedirectResponse("/admin", status_code=303)
    linhas = banco.consultar(
        "SELECT quando, email, motivo, detalhe, ip FROM recusas ORDER BY id DESC LIMIT 200")

    corpo = ['<h1>Recusas</h1><div class="painel">'
             '<p style="color:var(--tenue);font-size:13px;margin:0 0 14px">'
             'É aqui que o abuso aparece: a mesma conta tentando muitos aparelhos, '
             'senha errada em série, licença vencida insistindo.</p>'
             '<table><tr><th>quando</th><th>conta</th><th>motivo</th>'
             '<th>detalhe</th><th>ip</th></tr>']
    for l in linhas:
        corpo.append(
            f'<tr><td>{escape(l["quando"][:16].replace("T", " "))}</td>'
            f'<td>{escape(l["email"] or "—")}</td><td>{escape(l["motivo"])}</td>'
            f'<td>{escape(l["detalhe"] or "")}</td><td>{escape(l["ip"] or "")}</td></tr>')
    corpo.append("</table></div>")
    if not linhas:
        corpo.append('<div class="painel vazio">nada recusado ainda</div>')
    return _pagina("Recusas", "".join(corpo), admin["email"], "recusas")
