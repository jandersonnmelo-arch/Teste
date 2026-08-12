import json
from datetime import date
from pathlib import Path
import requests
import streamlit as st

st.set_page_config(page_title="Teste API-SPORTS", page_icon="🟣", layout="wide")

def get_secret(name, default=""):
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default

API_KEY = get_secret("API_FOOTBALL_KEY", "") or get_secret("API_SPORTS_KEY", "")
BASE = "https://v3.football.api-sports.io"
DATA_DIR = Path("./dados_teste_api_sports")
DATA_DIR.mkdir(exist_ok=True)
SAVE = DATA_DIR / "partidas_enriquecidas.json"

def load_saved():
    if not SAVE.exists():
        return {}
    try:
        return json.loads(SAVE.read_text(encoding="utf-8"))
    except Exception:
        return {}

def save_saved(data):
    tmp = SAVE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(SAVE)

def api_get(endpoint, params):
    if not API_KEY:
        return None, {"message": "Secret API_FOOTBALL_KEY/API_SPORTS_KEY não encontrado."}
    try:
        r = requests.get(
            f"{BASE}/{endpoint}",
            headers={"x-apisports-key": API_KEY, "Accept": "application/json"},
            params=params, timeout=30
        )
    except requests.RequestException as e:
        return None, {"message": f"Falha de conexão: {e}"}
    meta = {
        "http": r.status_code,
        "restante": r.headers.get("x-ratelimit-requests-remaining"),
        "limite": r.headers.get("x-ratelimit-requests-limit"),
    }
    try:
        payload = r.json()
    except ValueError:
        return None, {**meta, "message": f"Resposta não-JSON: {r.text[:300]}"}
    if r.status_code != 200:
        return None, {**meta, "message": f"HTTP {r.status_code}", "payload": payload}
    if payload.get("errors"):
        return None, {**meta, "message": f"Erros da API: {payload['errors']}", "payload": payload}
    return payload, meta

def resumo(item):
    f = item.get("fixture", {}) or {}
    t = item.get("teams", {}) or {}
    l = item.get("league", {}) or {}
    g = item.get("goals", {}) or {}
    h = (t.get("home", {}) or {}).get("name", "?")
    a = (t.get("away", {}) or {}).get("name", "?")
    return {
        "id": f.get("id"), "data": str(f.get("date", ""))[:19],
        "competicao": l.get("name", "?"), "casa": h, "fora": a,
        "status": (f.get("status", {}) or {}).get("short", ""),
        "placar": f"{g.get('home', '-')} x {g.get('away', '-')}",
    }

def validate_detail(payload, fixture_id):
    rows = payload.get("response", []) if isinstance(payload, dict) else []
    if not rows:
        return None, "A API respondeu sem nenhum fixture no detalhamento."
    for item in rows:
        if str((item.get("fixture", {}) or {}).get("id")) == str(fixture_id):
            return item, None
    return None, f"A API respondeu, mas não devolveu o fixture {fixture_id}."

st.title("🟣 Teste limpo — API-SPORTS")
st.caption("Protótipo independente para diagnosticar descoberta, enriquecimento e persistência.")

if not API_KEY:
    st.error("Configure o Secret API_FOOTBALL_KEY ou API_SPORTS_KEY.")
    st.stop()

with st.sidebar:
    st.success("API-SPORTS conectada")
    st.markdown("**Regras do teste**")
    st.write("• Nenhuma chamada automática ao abrir.")
    st.write("• 1 chamada para descobrir as partidas da data.")
    st.write("• 1 chamada para o fixture selecionado.")
    st.write("• Sem retry automático.")
    st.write("• Resposta vazia nunca vira 'enriquecida'.")
    st.write("• Laterais e tiros de meta ficam manuais.")

if "fixtures" not in st.session_state:
    st.session_state.fixtures = []

st.subheader("1️⃣ Buscar partidas")
d = st.date_input("Data", value=date.today(), format="DD/MM/YYYY")

if st.button("🔎 Buscar partidas desta data", type="primary"):
    with st.spinner("Consultando a API-SPORTS..."):
        payload, meta = api_get("fixtures", {"date": d.isoformat()})
    if payload is None:
        st.error(meta["message"])
        st.json(meta)
    else:
        st.session_state.fixtures = payload.get("response", []) or []
        st.success(f"Retornaram {payload.get('results', 0)} partidas.")
        if meta.get("restante"):
            st.caption(f"Quota restante informada pela API: {meta['restante']}")

fixtures = st.session_state.fixtures

if not fixtures:
    st.info("Escolha a data e clique em 'Buscar partidas desta data'.")
    st.stop()

options, mapping = [], {}
for item in fixtures:
    r = resumo(item)
    if not r["id"]:
        continue
    label = f"{r['data'].replace('T',' ')} | {r['casa']} x {r['fora']} | {r['competicao']} | ID {r['id']}"
    options.append(label)
    mapping[label] = item

st.subheader("2️⃣ Selecionar partida")
selected = st.selectbox("Partida", options)
catalog = mapping[selected]
r = resumo(catalog)
fid = r["id"]
st.info(f"Fixture identificado: **{fid}** — {r['casa']} x {r['fora']} — {r['competicao']}")

saved = load_saved()
item = saved.get(str(fid))

if item is None:
    st.warning("🟡 Esta partida ainda não foi enriquecida neste teste.")
    if st.button("🟣 Enriquecer somente esta partida", type="primary"):
        with st.spinner(f"Buscando detalhes do fixture {fid}..."):
            payload, meta = api_get("fixtures", {"id": str(fid)})
        if payload is None:
            st.error("A chamada foi feita, mas retornou erro. Nada foi salvo.")
            st.json(meta)
        else:
            item, err = validate_detail(payload, fid)
            if err:
                st.error(err + " Nada foi salvo como enriquecido.")
                st.write(f"HTTP: {meta.get('http')} · Results: {payload.get('results', 0)}")
                st.json(payload)
            else:
                item["_completo_validado"] = True
                item["_origem_teste"] = "fixtures?id"
                item["_salvo_em"] = str(date.today())
                saved[str(fid)] = item
                save_saved(saved)
                st.success(f"✅ Fixture {fid} validado e persistido.")
                st.rerun()
else:
    st.success(f"✅ Fixture {fid} já está persistido neste teste.")

if item:
    t = item.get("teams", {}) or {}
    g = item.get("goals", {}) or {}
    l = item.get("league", {}) or {}
    st.subheader("3️⃣ Dados retornados")
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Eventos", len(item.get("events",[]) or []))
    c2.metric("Lineups", len(item.get("lineups",[]) or []))
    c3.metric("Estatísticas", len(item.get("statistics",[]) or []))
    c4.metric("Jogadores", len(item.get("players",[]) or []))
    st.write(f"**{(t.get('home',{}) or {}).get('name','?')} {g.get('home','-')} × {g.get('away','-')} {(t.get('away',{}) or {}).get('name','?')}**")
    st.write(f"Competição: **{l.get('name','?')}** · Fixture: **{fid}**")

    st.markdown("### ⚽ Eventos")
    events=[]
    for e in item.get("events",[]) or []:
        events.append({
            "Min": (e.get("time",{}) or {}).get("elapsed"),
            "Time": (e.get("team",{}) or {}).get("name",""),
            "Jogador": (e.get("player",{}) or {}).get("name",""),
            "Tipo": e.get("type"), "Detalhe": e.get("detail")
        })
    if events:
        st.dataframe(events, use_container_width=True, hide_index=True)
    else:
        st.info("A API não retornou eventos.")

    st.markdown("### 👥 Escalações")
    lineups=item.get("lineups",[]) or []
    if lineups:
        for x in lineups:
            st.write(f"**{(x.get('team',{}) or {}).get('name','?')}** — {len(x.get('startXI',[]) or [])} titulares")
    else:
        st.info("A API não retornou escalações.")

    st.markdown("### 📊 Estatísticas das equipes")
    stats=item.get("statistics",[]) or []
    if stats:
        for x in stats:
            st.write(f"**{(x.get('team',{}) or {}).get('name','?')}**")
            st.dataframe(
                [{"Estatística":s.get("type"),"Valor":s.get("value")} for s in x.get("statistics",[]) or []],
                use_container_width=True, hide_index=True
            )
    else:
        st.info("A API não retornou estatísticas.")

    st.markdown("### ✍️ Complementos manuais")
    st.caption("Somente laterais e tiros de meta serão preenchidos manualmente.")
    h=(t.get("home",{}) or {}).get("name","Mandante")
    a=(t.get("away",{}) or {}).get("name","Visitante")
    c1,c2=st.columns(2)
    with c1:
        st.number_input(f"Laterais — {h}", min_value=0, step=1, key=f"lh_{fid}")
        st.number_input(f"Tiros de meta — {h}", min_value=0, step=1, key=f"mh_{fid}")
    with c2:
        st.number_input(f"Laterais — {a}", min_value=0, step=1, key=f"la_{fid}")
        st.number_input(f"Tiros de meta — {a}", min_value=0, step=1, key=f"ma_{fid}")

with st.expander("🔎 Diagnóstico"):
    st.write("Não há chamada escondida, lote automático ou retry. O resultado só é salvo depois de confirmar que o fixture solicitado veio na resposta.")
