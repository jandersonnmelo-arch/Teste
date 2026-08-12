import base64
import json
from datetime import date, datetime
import requests
import streamlit as st


# ============================================================
# CONFIGURAÇÃO
# ============================================================

st.set_page_config(
    page_title="Teste limpo — API-SPORTS",
    page_icon="🟣",
    layout="wide",
)

BASE_API = "https://v3.football.api-sports.io"

# Repositório onde o teste está hospedado
GITHUB_OWNER = "jandersonnmelo-arch"
GITHUB_REPO = "Teste"
GITHUB_BRANCH = "main"

# Arquivo persistente
GITHUB_FILE = "dados_app/cache.json"


# ============================================================
# SECRETS
# ============================================================

def get_secret(name, default=""):
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


API_KEY = (
    get_secret("API_SPORTS_KEY")
    or get_secret("API_FOOTBALL_KEY")
)

GITHUB_TOKEN = get_secret("GITHUB_TOKEN")


# ============================================================
# ESTADO PADRÃO DO CACHE
# ============================================================

def empty_cache():
    return {
        "version": 1,
        "api_calls": 0,
        "last_api_call": None,
        "date_searches": {},
        "fixtures": {},
        "details": {},
    }


# ============================================================
# GITHUB — LEITURA
# ============================================================

def github_headers():
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "X-GitHub-Api-Version": "2026-03-10",
    }


def github_file_url():
    return (
        f"https://api.github.com/repos/"
        f"{GITHUB_OWNER}/{GITHUB_REPO}/contents/{GITHUB_FILE}"
    )


def github_load_cache():
    """
    Lê dados_app/cache.json do GitHub.
    Não consome nenhuma chamada da API-Sports.
    """

    if not GITHUB_TOKEN:
        return empty_cache(), None, "GITHUB_TOKEN não configurado."

    try:
        r = requests.get(
            github_file_url(),
            headers=github_headers(),
            params={"ref": GITHUB_BRANCH},
            timeout=20,
        )

        if r.status_code == 404:
            return empty_cache(), None, None

        if not r.ok:
            return (
                empty_cache(),
                None,
                f"GitHub GET {r.status_code}: {r.text[:500]}",
            )

        obj = r.json()
        encoded = obj.get("content", "")

        content = base64.b64decode(
            encoded.replace("\n", "")
        ).decode("utf-8")

        data = json.loads(content)

        if not isinstance(data, dict):
            data = empty_cache()

        return data, obj.get("sha"), None

    except Exception as e:
        return empty_cache(), None, str(e)


# ============================================================
# GITHUB — GRAVAÇÃO
# ============================================================

def github_save_cache(cache, current_sha=None):
    """
    Cria ou atualiza dados_app/cache.json no GitHub.
    """

    if not GITHUB_TOKEN:
        return False, "GITHUB_TOKEN não configurado."

    try:
        content = json.dumps(
            cache,
            ensure_ascii=False,
            indent=2,
        )

        encoded = base64.b64encode(
            content.encode("utf-8")
        ).decode("ascii")

        payload = {
            "message": "Atualiza cache persistente da API-Sports",
            "content": encoded,
            "branch": GITHUB_BRANCH,
        }

        if current_sha:
            payload["sha"] = current_sha

        r = requests.put(
            github_file_url(),
            headers=github_headers(),
            json=payload,
            timeout=20,
        )

        if not r.ok:
            return (
                False,
                f"GitHub PUT {r.status_code}: {r.text[:500]}",
            )

        return True, None

    except Exception as e:
        return False, str(e)


# ============================================================
# API-SPORTS
# ============================================================

def api_get(endpoint, params):
    """
    ÚNICO ponto do aplicativo que pode chamar a API-Sports.
    """

    if not API_KEY:
        return None, "API-Sports key não configurada."

    headers = {
        "x-apisports-key": API_KEY
    }

    try:
        r = requests.get(
            f"{BASE_API}/{endpoint}",
            headers=headers,
            params=params,
            timeout=30,
        )

        try:
            payload = r.json()
        except Exception:
            payload = {
                "errors": {
                    "http": r.status_code,
                    "text": r.text[:500],
                }
            }

        if not r.ok:
            return None, payload

        return payload, None

    except Exception as e:
        return None, str(e)


# ============================================================
# CONTROLE DE CHAMADAS
# ============================================================

def register_api_call(cache):
    cache["api_calls"] = int(cache.get("api_calls", 0)) + 1
    cache["last_api_call"] = datetime.utcnow().isoformat() + "Z"


# ============================================================
# CACHE DE PARTIDAS POR DATA
# ============================================================

def search_fixtures(cache, sha, selected_date):
    """
    Procura primeiro no GitHub.

    Se já existir a data no cache:
        NÃO chama API-Sports.

    Caso contrário:
        faz UMA chamada /fixtures?date=...
        e salva o resultado.
    """

    key = selected_date.isoformat()

    cached = cache.get("date_searches", {}).get(key)

    if cached is not None:
        return cached, sha, False, None

    payload, error = api_get(
        "fixtures",
        {"date": key},
    )

    if error:
        return None, sha, True, error

    response = payload.get("response", [])

    register_api_call(cache)

    cache.setdefault("date_searches", {})[key] = response

    # Indexa cada fixture pelo ID
    for item in response:
        fixture = item.get("fixture", {})
        fixture_id = fixture.get("id")

        if fixture_id:
            cache.setdefault("fixtures", {})[
                str(fixture_id)
            ] = item

    ok, save_error = github_save_cache(cache, sha)

    if not ok:
        return response, sha, True, save_error

    # Depois do PUT o SHA mudou.
    # Na próxima operação o app recarregará o arquivo.
    return response, None, True, None


# ============================================================
# DETALHAMENTO DE UMA PARTIDA
# ============================================================

def enrich_fixture(cache, sha, fixture_id):
    """
    Procura primeiro no cache persistente.

    Se já houver detalhes:
        NÃO chama API-Sports.

    Se não houver:
        faz UMA chamada /fixtures?id=...
    """

    key = str(fixture_id)

    existing = cache.get("details", {}).get(key)

    if existing is not None:
        return existing, sha, False, None

    payload, error = api_get(
        "fixtures",
        {"id": fixture_id},
    )

    if error:
        return None, sha, True, error

    response = payload.get("response", [])

    register_api_call(cache)

    if not response:
        # Guardamos inclusive o resultado vazio.
        # Isso é importante para não ficar repetindo
        # chamadas infinitamente para uma partida sem retorno.
        cache.setdefault("details", {})[key] = {
            "response": [],
            "errors": payload.get("errors", {}),
            "empty": True,
        }
    else:
        cache.setdefault("details", {})[key] = {
            "response": response,
            "errors": payload.get("errors", {}),
            "empty": False,
        }

    ok, save_error = github_save_cache(cache, sha)

    if not ok:
        return (
            cache["details"][key],
            sha,
            True,
            save_error,
        )

    return cache["details"][key], None, True, None


# ============================================================
# CARREGAMENTO INICIAL
# ============================================================

if not API_KEY:
    st.error(
        "Configure o Secret API_SPORTS_KEY "
        "ou API_FOOTBALL_KEY."
    )
    st.stop()

if not GITHUB_TOKEN:
    st.warning(
        "O Secret GITHUB_TOKEN ainda não está configurado. "
        "O teste poderá consultar a API-Sports, mas não terá "
        "persistência real no GitHub."
    )

cache, cache_sha, cache_error = github_load_cache()

if cache_error:
    st.error(f"Erro ao ler o cache do GitHub: {cache_error}")


# ============================================================
# INTERFACE
# ============================================================

st.title("🟣 Teste limpo — API-SPORTS")

st.caption(
    "Protótipo independente para diagnosticar "
    "descoberta, enriquecimento e persistência."
)


# ============================================================
# PAINEL DE CONTROLE
# ============================================================

st.subheader("📊 Controle de chamadas")

c1, c2, c3 = st.columns(3)

with c1:
    st.metric(
        "Chamadas API-Sports feitas",
        cache.get("api_calls", 0),
    )

with c2:
    st.metric(
        "Datas armazenadas",
        len(cache.get("date_searches", {})),
    )

with c3:
    st.metric(
        "Partidas enriquecidas",
        len(cache.get("details", {})),
    )


if cache.get("last_api_call"):
    st.caption(
        f"Última chamada API-Sports: "
        f"{cache['last_api_call']}"
    )


# ============================================================
# BUSCAR PARTIDAS
# ============================================================

st.subheader("1️⃣ Buscar partidas")

selected_date = st.date_input(
    "Data",
    value=date.today(),
)

if st.button(
    "🔎 Buscar partidas desta data",
    type="primary",
):

    # Recarrega o cache antes da operação.
    cache, cache_sha, cache_error = github_load_cache()

    if cache_error:
        st.error(cache_error)
        st.stop()

    with st.spinner("Consultando cache/API..."):

        fixtures, cache_sha, api_was_called, error = (
            search_fixtures(
                cache,
                cache_sha,
                selected_date,
            )
        )

    if error:
        st.error(str(error))

    elif fixtures is None:
        st.error("Não foi possível obter as partidas.")

    else:
        if api_was_called:
            st.success(
                f"Retornaram {len(fixtures)} partidas. "
                "Esta operação consultou a API-Sports."
            )
        else:
            st.info(
                f"Retornaram {len(fixtures)} partidas "
                "a partir do CACHE — nenhuma chamada "
                "à API-Sports foi feita."
            )

        st.session_state["fixtures"] = fixtures
        st.session_state["selected_date"] = (
            selected_date.isoformat()
        )


# ============================================================
# SELEÇÃO DA PARTIDA
# ============================================================

fixtures = st.session_state.get("fixtures", [])

if fixtures:

    st.subheader("2️⃣ Selecionar partida")

    options = []

    for item in fixtures:

        fixture = item.get("fixture", {})
        league = item.get("league", {})
        teams = item.get("teams", {})

        fixture_id = fixture.get("id")

        home = (
            teams.get("home", {})
            .get("name", "Casa")
        )

        away = (
            teams.get("away", {})
            .get("name", "Fora")
        )

        league_name = league.get(
            "name",
            "Competição desconhecida",
        )

        date_text = fixture.get(
            "date",
            "",
        )

        label = (
            f"{date_text} | "
            f"{home} x {away} | "
            f"{league_name} | "
            f"ID {fixture_id}"
        )

        options.append(
            (label, fixture_id)
        )

    labels = [
        item[0]
        for item in options
    ]

    selected_label = st.selectbox(
        "Partida",
        labels,
    )

    selected_fixture_id = dict(options)[
        selected_label
    ]

    st.info(
        f"Fixture identificado: "
        f"{selected_fixture_id}"
    )

    cached_detail = cache.get(
        "details",
        {},
    ).get(
        str(selected_fixture_id)
    )

    if cached_detail is not None:

        if cached_detail.get("empty"):
            st.warning(
                "Esta partida já foi consultada "
                "e a API-Sports retornou resposta vazia. "
                "O resultado está persistido no GitHub."
            )
        else:
            st.success(
                "🟢 Esta partida já está enriquecida "
                "no cache persistente. "
                "Não é necessário fazer outra chamada."
            )

    else:

        st.warning(
            "🟡 Esta partida ainda não foi enriquecida "
            "neste teste."
        )

        if st.button(
            "🟣 Enriquecer somente esta partida",
            type="primary",
        ):

            # Recarrega o cache imediatamente antes
            # de gastar uma possível chamada.
            cache, cache_sha, cache_error = (
                github_load_cache()
            )

            if cache_error:
                st.error(cache_error)
                st.stop()

            with st.spinner(
                "Verificando cache e API-Sports..."
            ):

                details, cache_sha, api_was_called, error = (
                    enrich_fixture(
                        cache,
                        cache_sha,
                        selected_fixture_id,
                    )
                )

            if error:
                st.error(str(error))

            elif api_was_called:
                st.success(
                    "Consulta à API-Sports realizada "
                    "e resultado salvo no GitHub."
                )

                st.rerun()

            else:
                st.info(
                    "O resultado já estava no cache. "
                    "Nenhuma chamada à API-Sports foi feita."
                )

                st.rerun()


# ============================================================
# DIAGNÓSTICO
# ============================================================

with st.expander("🔎 Diagnóstico"):

    st.write(
        "O objetivo deste teste é separar três coisas:"
    )

    st.write(
        "1. descoberta da partida;"
    )

    st.write(
        "2. enriquecimento da partida;"
    )

    st.write(
        "3. persistência do resultado."
    )

    st.write(
        "O contador acima registra somente chamadas "
        "feitas ao endpoint API-Sports pelo próprio app."
    )

    st.write(
        "O cache persistente fica em "
        f"`{GITHUB_FILE}`."
    )

    st.write(
        "Recarregar o Streamlit não deve apagar "
        "esse arquivo."
    )

    st.write(
        "Se uma partida já estiver em `details`, "
        "o botão não deve gerar uma nova chamada."
    )
