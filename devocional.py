"""Devocional diário do Brain.
Monta a nota do dia (liturgia + santos) e as notas do santoral, depois avisa no Telegram.
Fontes e regras: dominios/espiritualidade/devocional/fontes.md e o CLAUDE.md do domínio.
Nunca inventa texto: o que não veio da fonte fica marcado como indisponível.

Uso:  python devocional.py                 (hoje)
      python devocional.py 2026-09-12      (data específica; aceita DD-MM-AAAA)
      python devocional.py --no-send       (não manda Telegram)
      python devocional.py --out DIR       (modo nuvem: grava em DIR/devocional/AAAA e DIR/santoral,
                                            não toca no santoral existente, imprime manifesto JSON)
      python devocional.py --celebrado ARQUIVO AAAA-MM-DD   (acrescenta a data em `celebrado:` de uma nota
                                            de santo existente; aceita YAML inline ou em bloco)
      python devocional.py --catchup       (PC ao ligar: cria as notas que faltam nos ultimos 7 dias, sem Telegram)
      python devocional.py --telegram-only (nuvem: nao grava nada; manda resumo + leituras integrais no Telegram)
      python devocional.py --drive         (grava pela API do Drive; superado em 12/09, ver ARQUITETURA.md)
"""
import re, sys, json, datetime as dt, urllib.request, urllib.error
from pathlib import Path
from htmltree import parse, clean

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = Path(__file__).resolve().parent
BRAIN = HERE.parent.parent
ESP = BRAIN / "dominios" / "espiritualidade"
DEVOC = ESP / "devocional"
SANTORAL = ESP / "santoral"
LOG = BRAIN / "automacoes" / "logs" / "devocional.log"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Brain-devocional/1.0"}
PPR = "https://padrepauloricardo.org/liturgia/{d:%d-%m-%Y}"
CN_HOME = "https://santo.cancaonova.com/"
CN_DIA = "https://santo.cancaonova.com/?sDia={d.day}&sMes={d:%m}&sAno={d:%Y}"
DRIVE_DEVOC = "1UOoiMbNvWL74jNy1asvRnhjzl2MjgEZu"      # Brain/dominios/espiritualidade/devocional
DRIVE_SANTORAL = "1AeCxU6vta7qmoreQ4lumsCPemRVrc_gC"   # Brain/dominios/espiritualidade/santoral


# ---------- util ----------
def fetch(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:
        log(f"FALHA {url} -> {e}")
        return None


def log(msg):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")
    print(msg)


def versos(t):
    """'14Meus caríssimos' -> '14 Meus caríssimos'. Só formatação; o texto não muda."""
    return re.sub(r"(?<![\w,.\-–])(\d{1,3})(?=[A-Za-zÀ-ú«“\"'])", r"\1 ", t)


def paras(node):
    """Parágrafos preservando quebras internas (<br>) — importante no salmo."""
    out = []
    for p in node.findall("p"):
        t = clean(p.text())
        if t:
            out.append(versos(t))
    return out


def yaml_list(items):
    return "[" + ", ".join(json.dumps(i, ensure_ascii=False) for i in items) + "]"


# ---------- liturgia (Pe. Paulo Ricardo) ----------
TEMPOS = ["Tempo Comum", "Advento", "Natal", "Quaresma", "Tríduo", "Páscoa", "Pascal"]
CORES = {"green": "verde", "purple": "roxo", "violet": "roxo", "white": "branco",
         "red": "vermelho", "rose": "rosa", "pink": "rosa"}


def pascoa(ano):
    """Domingo de Páscoa (algoritmo de Meeus/Jones/Butcher, calendário gregoriano)."""
    a, b, c = ano % 19, ano // 100, ano % 100
    d_, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d_ - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = ((h + l - 7 * m + 114) % 31) + 1
    return dt.date(ano, mes, dia)


def tempo_por_data(d):
    """Tempo litúrgico calculado pelo calendário romano geral. Determinístico, não é palpite."""
    P = pascoa(d.year)
    natal = dt.date(d.year, 12, 25)
    advento = natal - dt.timedelta(days=natal.weekday() + 1 + 21)  # 4º domingo antes do Natal
    if d >= advento:
        return "Advento" if d < natal else "Natal"
    # Natal termina no Batismo do Senhor: domingo após a Epifania (Epifania = domingo entre 2 e 8/jan no Brasil)
    jan2 = dt.date(d.year, 1, 2)
    epifania = jan2 + dt.timedelta(days=(6 - jan2.weekday()) % 7)  # domingo entre 2 e 8/jan
    batismo = epifania + dt.timedelta(days=1 if epifania.day in (7, 8) else 7)
    if d <= batismo:
        return "Natal"
    cinzas = P - dt.timedelta(days=46)
    if cinzas <= d < P - dt.timedelta(days=3):
        return "Quaresma"
    if P - dt.timedelta(days=3) <= d < P:
        return "Tríduo"
    if P <= d <= P + dt.timedelta(days=49):
        return "Páscoa"
    return "Tempo Comum"


def liturgia(d):
    url = PPR.format(d=d)
    src = fetch(url)
    if not src:
        return {"ok": False, "url": url}
    doc = parse(src)
    tit = doc.find(cls="liturgy-title")
    titulo = clean(tit.text()) if tit else "indefinido"
    cor_el = doc.find(cls="liturgy-color")
    cor = "indefinida"
    if cor_el:
        for c in cor_el.cls():
            if c in CORES:
                cor = CORES[c]
    tempo = next((t for t in TEMPOS if t.lower() in titulo.lower()), None)
    if tempo == "Pascal":
        tempo = "Páscoa"
    if tempo is None:
        tempo = tempo_por_data(d)  # festa/solenidade não traz o tempo no título; calcula pelo calendário
    grau = "indefinido"
    for g in ("Solenidade", "Festa", "Memória facultativa", "Memória"):
        if g.lower() in titulo.lower():
            grau = g.lower()
            break
    leituras, meditacao = [], None
    for acc in doc.findall(cls="reading-accordion"):
        tipo_el = acc.find(cls="reading-type")
        tipo = clean(tipo_el.text()) if tipo_el else "?"
        ref_el = acc.find(cls="reading-reference")
        ref = clean(ref_el.text()) if ref_el else ""
        body = acc.find(cls="reading-body")
        ps = paras(body) if body else []
        if body and "meditation" in body.cls():
            mt = acc.find(cls="reading-title")
            meditacao = {"titulo": clean(mt.text()) if mt else "Meditação",
                         "primeiro": primeiro_paragrafo(ps), "url": url}
            continue
        tit_el = acc.find(cls="reading-title")
        titulo_l = clean(tit_el.text()) if tit_el else ""
        if ref and titulo_l.endswith(ref):
            titulo_l = titulo_l[: -len(ref)].strip()
        refrao = None
        if "salmo" in tipo.lower():
            rf = acc.find(cls="reading-refrain")
            if rf:
                refrao = clean(rf.text())
                if ref and refrao.endswith(ref):
                    refrao = refrao[: -len(ref)].strip()
            if ps and refrao and ps[0] == refrao:
                ps = ps[1:]
        leituras.append({"tipo": tipo, "titulo": titulo_l, "ref": ref, "refrao": refrao, "paragrafos": ps})
    return {"ok": True, "url": url, "titulo": titulo, "cor": cor, "tempo": tempo, "grau": grau,
            "leituras": leituras, "meditacao": meditacao}


def primeiro_paragrafo(ps):
    """A meditação repete o evangelho antes de começar. Pula isso e pega o 1º parágrafo real."""
    skip = ("evangelho de nosso senhor", "(", "naquele tempo", "palavra da salvação", "glória a vós")
    for p in ps:
        if p.lower().startswith(skip) or len(p.split()) < 20:
            continue
        return p
    return ps[0] if ps else None


# ---------- santos (Canção Nova) ----------
def nome_arquivo(nome):
    """Nome do santo por extenso vira nome do arquivo (decisão 12/09): legível e linkável no Obsidian.
    Só tira o que o Obsidian/Windows não aceitam em nome de arquivo."""
    n = re.sub(r'[\\/:*?"<>|#^\[\]]', "-", nome)
    return re.sub(r"\s+", " ", n).strip(" .")


def slug_of(url):
    m = re.search(r"/santo/([^/?#]+)", url or "")
    return m.group(1) if m else None


def santo_de(doc, url):
    h1s = [clean(h.text()) for h in doc.findall("h1")]
    nome = next((h for h in reversed(h1s) if "Santo do Dia" not in h), None)
    body = doc.find(cls="content-santo")
    return {"nome": nome or "?", "slug": slug_of(url), "url": url, "paragrafos": paras(body) if body else []}


def hoje_sp():
    """Data de hoje em São Paulo (UTC-3 fixo; o Brasil não tem horário de verão desde 2019).
    O sandbox da nuvem roda em UTC: entre 21h e 24h de SP, date.today() já seria amanhã."""
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=-3))).date()


MESES = ["", "janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
         "setembro", "outubro", "novembro", "dezembro"]


def celebrado_em(s, d):
    """A biografia da Canção Nova termina com 'Outros santos e beatos celebrados em DD de mês'.
    Só aceita o santo em destaque se essa frase bater com a data pedida."""
    texto = " ".join(s["paragrafos"])
    return re.search(rf"celebrados?\s+em\s+{d.day}\s+de\s+{MESES[d.month]}", texto, flags=re.I) is not None


def santos(d):
    out, vistos = [], set()
    src = fetch(CN_DIA.format(d=d)) or fetch(CN_HOME)
    if not src:
        return {"ok": False, "lista": []}
    doc = parse(src)
    dia_el = doc.find(cls="dia-liturgia")
    dia_pagina = clean(dia_el.text()) if dia_el else ""
    # 1) santo em destaque — só vale para HOJE: a home sempre mostra o destaque do dia corrente,
    #    mesmo quando se pede outra data pela query string.
    og = next((m.attrs.get("content") for m in doc.findall("meta") if m.attrs.get("property") == "og:url"), "")
    if slug_of(og):
        s = santo_de(doc, og.split("?")[0])
        if celebrado_em(s, d):  # o destaque da home vira para o dia seguinte já à noite; a prova é a frase do texto
            vistos.add(s["slug"])
            out.append(s)
        else:
            log(f"santos: destaque da home ignorado ({s['slug']}) — texto não confirma {d:%d/%m}")
    # 2) santo(s) do calendário para o dia
    pat = f"sDia={d.day}&sMes={d:%m}&sAno={d:%Y}"
    links = {a.attrs["href"].split("?")[0] for a in doc.findall("a")
             if pat in a.attrs.get("href", "") and a.attrs["href"].startswith("https://santo.cancaonova.com/santo/")}
    for u in sorted(links):
        sl = slug_of(u)
        if sl in vistos:
            continue
        page = fetch(u + "?" + pat)
        if page:
            s = santo_de(parse(page), u)
            vistos.add(sl)
            out.append(s)
    return {"ok": True, "lista": out}


# ---------- notas ----------
def nota_dia(d, lit, sts):
    refs = [l["ref"] for l in lit.get("leituras", []) if l.get("ref")] if lit["ok"] else []
    fontes = [lit["url"]] + [s["url"] for s in sts["lista"]]
    links = [f"[[santoral/{nome_arquivo(s['nome'])}]]" for s in sts["lista"] if s["slug"]]
    fm = ["---", f"data: {d:%Y-%m-%d}",
          f"dia_liturgico: {json.dumps(lit.get('titulo', 'indefinido'), ensure_ascii=False)}",
          f"tempo: {lit.get('tempo', 'indefinido')}", f"cor: {lit.get('cor', 'indefinida')}",
          f"santos: {yaml_list(links)}", f"leituras: {yaml_list(refs)}",
          f"fontes: {yaml_list(fontes)}", "---", ""]
    body = [f"# {d:%d/%m/%Y} — {lit.get('titulo', 'indefinido')}", "", "## Liturgia do dia", ""]
    if not lit["ok"]:
        body += [f"⚠️ fonte indisponível — {lit['url']}", ""]
    for l in lit.get("leituras", []):
        body.append(f"### {l['tipo']} · {l['ref']}".rstrip(" ·"))
        if l["titulo"]:
            body.append(f"_{l['titulo']}_")
        body.append("")
        if l["refrao"]:
            body += [f"**R.** {l['refrao']}", ""]
        for p in l["paragrafos"]:
            body += [p.replace("\n", "  \n"), ""]
    m = lit.get("meditacao")
    if m:
        body += ["### Meditação do Pe. Paulo Ricardo", f"**{m['titulo']}**", "",
                 (m["primeiro"] or "⚠️ texto não localizado") + f" — [ler íntegra]({m['url']})", ""]
    body += ["## Santos do dia", ""]
    if not sts["ok"]:
        body.append("⚠️ fonte indisponível — santo.cancaonova.com")
    for s in sts["lista"]:
        linha = next((p for p in s["paragrafos"] if len(p.split()) >= 8), "")
        linha = re.sub(r"^(História|Origens)\s*", "", linha)
        linha = linha.split(". ")[0].strip(".") + "." if linha else ""
        body.append(f"- [[santoral/{nome_arquivo(s['nome'])}]] — {linha}")
    body += ["", "## Meditação", "", "_(meu espaço — a IA não escreve aqui)_", ""]
    return "\n".join(fm + body)


def nota_santo(d, s, grau):
    fm = ["---", f"nome: {json.dumps(s['nome'], ensure_ascii=False)}", f"slug: {s['slug']}",
          f"celebracao: {d:%d-%m}", f"grau: {grau}", f"fontes: {yaml_list([s['url']])}",
          f"celebrado: [{d:%Y-%m-%d}]", f"criado: {d:%Y-%m-%d}", "---", ""]
    body = [f"# {s['nome']}", ""]
    for p in s["paragrafos"]:
        body += [p.replace("\n", "  \n"), ""]
    if not s["paragrafos"]:
        body += ["⚠️ fonte indisponível — biografia não extraída", ""]
    body += [f"Fonte: {s['url']}", "", "## Minhas notas", "", "_(meu espaço)_", ""]
    return "\n".join(fm + body)


def marca_celebrado(path, d):
    """Nota do santo já existe: só acrescenta a data em `celebrado:`. Nunca toca no resto.
    Aceita os dois formatos de YAML: inline (`celebrado: [a, b]`) e em bloco (`celebrado:` + linhas `  - a`),
    porque o Obsidian reescreve o frontmatter em bloco quando se edita propriedades."""
    txt = path.read_text(encoding="utf-8")
    hoje = f"{d:%Y-%m-%d}"
    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n", txt, flags=re.S)
    if not m:
        return False
    lines = m.group(1).split("\n")
    idx = [i for i, l in enumerate(lines) if l.startswith("celebrado:")]
    if not idx:
        lines.append(f"celebrado: [{hoje}]")
    else:
        i = idx[0]
        inline = re.match(r"^celebrado:\s*\[(.*?)\]\s*$", lines[i])
        if inline:
            datas = [x.strip().strip("\"'") for x in inline.group(1).split(",") if x.strip()]
            if hoje in datas:
                return False
            datas.append(hoje)
            lines[i] = f"celebrado: [{', '.join(datas)}]"
        else:
            j, datas = i + 1, []
            while j < len(lines) and re.match(r"^\s+-\s*", lines[j]):
                datas.append(lines[j].split("-", 1)[1].strip().strip("\"'"))
                j += 1
            if hoje in datas:
                return False
            lines.insert(j, f"  - {hoje}")
        for k in reversed(idx[1:]):  # chave duplicada por erro anterior: remove a extra
            del lines[k]
    path.write_text("---\n" + "\n".join(lines) + "\n---\n" + txt[m.end():], encoding="utf-8")
    return True


# ---------- telegram ----------
def resumo(d, lit, sts, nota_rel):
    cor = f" · {lit['cor']}" if lit.get("cor") not in (None, "indefinida") else ""
    L = [f"🕊️ {d:%d/%m} · {lit.get('titulo', 'indefinido')}{cor}"]
    for l in lit.get("leituras", []):
        L.append(f"• {l['tipo']}: {l['ref']}")
    m = lit.get("meditacao")
    if m:
        L.append(f"✝️ {m['titulo']} — {m['url']}")
    if sts["lista"]:
        L.append("🙏 " + " · ".join(s["nome"] for s in sts["lista"]))
    if not lit["ok"] or not sts["ok"]:
        L.append("⚠️ fonte indisponível — ver nota")
    L.append(f"📝 {nota_rel}")
    return "\n".join(L)


# ---------- Drive (modo --drive) ----------
def espelha_no_drive(d, out, nota, sts):
    """Grava no Drive o que o script gerou em `out`, com as mesmas regras do modo local:
    nota do dia só se não existir; santo novo criado; santo existente só ganha a data em `celebrado:`."""
    import tempfile, drive_lib as dr
    rel = {}
    ano_id = dr.ensure_folder(DRIVE_DEVOC, f"{d:%Y}")
    if dr.find(ano_id, nota.name):
        log(f"drive: nota do dia já existe: {nota.name} (não sobrescrevo)")
    else:
        r = dr.create(ano_id, nota.name, nota.read_bytes())
        ok = int(r.get("size", -1)) == nota.stat().st_size
        log(f"drive: nota criada {nota.name} ({r.get('size')} bytes{'' if ok else ' — TAMANHO DIFERE DO LOCAL'})")
    for s in sts["lista"]:
        if not s["slug"]:
            continue
        nome = f"{nome_arquivo(s['nome'])}.md"
        local = SANTORAL / nome
        ex = dr.find(DRIVE_SANTORAL, nome)
        if not ex:
            r = dr.create(DRIVE_SANTORAL, nome, local.read_bytes())
            log(f"drive: santoral criado '{nome[:-3]}' ({r.get('size')} bytes)")
            continue
        tmp = Path(tempfile.mkdtemp()) / nome
        tmp.write_bytes(dr.download(ex["id"]))
        if marca_celebrado(tmp, d):
            r = dr.update(ex["id"], tmp.read_bytes())
            log(f"drive: santoral '{nome[:-3]}' → celebrado += {d:%Y-%m-%d} ({r.get('size')} bytes)")
        else:
            log(f"drive: santoral '{nome[:-3]}' já marcado para {d:%Y-%m-%d}")


# ---------- telegram: envio completo ----------
def blocos_completos(d, lit, sts):
    """Leituras integrais + 1º parágrafo da meditação + santos, em blocos de até ~3900 chars."""
    partes = []
    for l in lit.get("leituras", []):
        t = f"📖 {l['tipo']} · {l['ref']}\n"
        if l["titulo"]:
            t += f"{l['titulo']}\n"
        if l["refrao"]:
            t += f"R. {l['refrao']}\n"
        t += "\n" + "\n\n".join(l["paragrafos"])
        partes.append(t)
    m = lit.get("meditacao")
    if m and m.get("primeiro"):
        partes.append(f"✝️ {m['titulo']}\n\n{m['primeiro']}\n\nÍntegra: {m['url']}")
    for s in sts["lista"]:
        bio = "\n\n".join(s["paragrafos"])
        partes.append(f"🙏 {s['nome']}\n\n{bio}\n\nFonte: {s['url']}")
    blocos, atual = [], ""
    for p in partes:
        if atual and len(atual) + len(p) + 2 > 3900:
            blocos.append(atual)
            atual = ""
        while len(p) > 3900:  # parte maior que um bloco: corta em parágrafo
            corte = p.rfind("\n\n", 0, 3900)
            corte = corte if corte > 0 else 3900
            blocos.append(p[:corte])
            p = p[corte:].lstrip("\n")
        atual = (atual + "\n\n" + p) if atual else p
    if atual:
        blocos.append(atual)
    return blocos


def envia_telegram(d, lit, sts, nota_rel, completo=False):
    from telegram_lib import api, chat_id
    cid = chat_id()
    api("sendMessage", {"chat_id": cid, "text": resumo(d, lit, sts, nota_rel), "disable_web_page_preview": "true"})
    n = 1
    if completo:
        for b in blocos_completos(d, lit, sts):
            api("sendMessage", {"chat_id": cid, "text": b, "disable_web_page_preview": "true"})
            n += 1
    log(f"telegram: {n} mensagem(ns) enviada(s)")


# ---------- pipeline de um dia ----------
def processa(d, send=True, out=None, drive=False, telegram_only=False):
    """Gera liturgia + santos para o dia `d` e grava conforme o modo. Devolve o caminho da nota."""
    base = out or BRAIN
    rel = lambda p: p.relative_to(base).as_posix()
    nota_rel_brain = f"dominios/espiritualidade/devocional/{d:%Y}/{d:%Y-%m-%d}.md"
    log(f"== devocional {d:%Y-%m-%d} ==")
    lit = liturgia(d)
    sts = santos(d)
    grau = lit.get("grau", "indefinido") if lit["ok"] else "indefinido"
    if telegram_only:
        envia_telegram(d, lit, sts, nota_rel_brain, completo=True)
        return None
    SANTORAL.mkdir(parents=True, exist_ok=True)
    for s in sts["lista"]:
        if not s["slug"]:
            continue
        p = SANTORAL / f"{nome_arquivo(s['nome'])}.md"
        if p.exists():
            if marca_celebrado(p, d):
                log(f"santoral: '{p.stem}' já existe → celebrado += {d:%Y-%m-%d}")
            else:
                log(f"santoral: '{p.stem}' já marcado para {d:%Y-%m-%d}")
        else:
            p.write_text(nota_santo(d, s, grau), encoding="utf-8")
            log(f"santoral: criado '{p.stem}'")
    pasta = DEVOC / f"{d:%Y}"
    pasta.mkdir(parents=True, exist_ok=True)
    nota = pasta / f"{d:%Y-%m-%d}.md"
    if nota.exists():
        log(f"nota do dia já existe: {nota.name} (não sobrescrevo)")
    else:
        nota.write_text(nota_dia(d, lit, sts), encoding="utf-8")
        log(f"nota criada: {rel(nota)}")
    if drive:
        espelha_no_drive(d, out, nota, sts)
    if out and not drive:
        (out / "telegram.txt").write_text(resumo(d, lit, sts, nota_rel_brain), encoding="utf-8")
        manifesto = {"data": f"{d:%Y-%m-%d}", "ano": f"{d:%Y}", "nota_dia": rel(nota),
                     "santoral": [{"arquivo": rel(SANTORAL / f"{nome_arquivo(s['nome'])}.md"), "nome": s["nome"]}
                                  for s in sts["lista"] if s["slug"]],
                     "telegram": resumo(d, lit, sts, nota_rel_brain),
                     "fontes_ok": {"liturgia": lit["ok"], "santos": sts["ok"]}}
        (out / "manifesto.json").write_text(json.dumps(manifesto, ensure_ascii=False, indent=2), encoding="utf-8")
        log("manifesto: manifesto.json")
    if send:
        envia_telegram(d, lit, sts, nota_rel_brain if drive else rel(nota), completo=False)
    return nota


# ---------- main ----------
def main(argv):
    global DEVOC, SANTORAL, LOG
    if "--celebrado" in argv:  # uso: --celebrado ARQUIVO AAAA-MM-DD
        i = argv.index("--celebrado")
        p, d = Path(argv[i + 1]), dt.date.fromisoformat(argv[i + 2])
        print("celebrado: acrescentado" if marca_celebrado(p, d) else "celebrado: já constava")
        return 0
    send = "--no-send" not in argv
    drive = "--drive" in argv
    telegram_only = "--telegram-only" in argv
    out = None
    if drive or telegram_only:
        import tempfile
        out = Path(tempfile.mkdtemp(prefix="brain-devocional-"))
        DEVOC, SANTORAL, LOG = out / "devocional", out / "santoral", out / "devocional.log"
    elif "--out" in argv:
        out = Path(argv[argv.index("--out") + 1]).resolve()
        DEVOC, SANTORAL, LOG = out / "devocional", out / "santoral", out / "devocional.log"
    args = [a for i, a in enumerate(argv[1:], 1) if not a.startswith("--") and argv[i - 1] != "--out"]
    d = hoje_sp()
    if args:
        a = args[0]
        d = (dt.datetime.strptime(a, "%Y-%m-%d") if a[4] == "-" else dt.datetime.strptime(a, "%d-%m-%Y")).date()
    if "--catchup" in argv:  # PC ao ligar: cria o que faltou nos últimos 7 dias, sem Telegram
        feitos = 0
        for k in range(6, -1, -1):
            dia = d - dt.timedelta(days=k)
            if (DEVOC / f"{dia:%Y}" / f"{dia:%Y-%m-%d}.md").exists():
                continue
            processa(dia, send=False, out=out)
            feitos += 1
        log(f"catchup: {feitos} dia(s) criado(s)")
        return 0
    processa(d, send=send, out=out, drive=drive, telegram_only=telegram_only)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
