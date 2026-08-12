import base64
import json
from datetime import date, datetime, timezone

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

GITHUB_OWNER = "jandersonnmelo-arch"
GITHUB_REPO = "Teste"
GITHUB_BRANCH = "main"

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
# CACHE PADRÃO
# ============================================================

def empty_cache():
    return {
        "version": 2,
        "api_calls": 0,
        "last_api_call": None,
        "date_searches": {},
        "fixtures": {},
        "details": {},
    }


def normalize_cache(data):
    """
    Garante que o cache tenha todas as estruturas esperadas.

    Importante:
    não descarta dados existentes.
    """

    if not isinstance(data, dict):
        data = {}

    cache = empty_cache()

    cache["version"] = data.get(
        "version",
        1,
    )

    cache["api_calls"] = int(
        data.get(
            "api_calls",
            0,
        )
    )

    cache["last_api_call"] = data.get(
        "last_api_call"
    )

    if isinstance(
        data.get("date_searches"),
        dict,
    ):
        cache["date_searches"] = data[
            "date_searches"
        ]

    if isinstance(
        data.get("fixtures"),
        dict,
    ):
        cache["fixtures"] = data[
            "fixtures"
        ]

    if isinstance(
        data.get("details"),
        dict,
    ):
        cache["details"] = data[
            "details"
        ]

    return cache


# ============================================================
# GITHUB
# ============================================================

def github_headers():
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def github_file_url():
    return (
        f"https://api.github.com/repos/"
        f"{GITHUB_OWNER}/{GITHUB_REPO}/contents/"
        f"{GITHUB_FILE}"
    )


# ============================================================
# GITHUB — LEITURA
# ============================================================

def github_load_cache():
    """
    Lê o cache persistente do GitHub.

    Retorno:
        cache, sha, erro

    IMPORTANTE:
    se houver erro de leitura, NÃO retorna um cache vazio
    para posterior gravação. Isso evita apagar dados.
    """

    if not GITHUB_TOKEN:
        return (
            empty_cache(),
            None,
            "GITHUB_TOKEN não configurado.",
        )

    try:

        response = requests.get(
            github_file_url(),
            headers=github_headers(),
            params={
                "ref": GITHUB_BRANCH
            },
            timeout=20,
        )

        # Arquivo ainda não existe.
        if response.status_code == 404:
            return (
                empty_cache(),
                None,
                None,
            )

        if not response.ok:
            return (
                None,
                None,
                (
                    f"GitHub GET {response.status_code}: "
                    f"{response.text[:500]}"
                ),
            )

        obj = response.json()

        encoded = obj.get(
            "content",
            "",
        )

        if not encoded:
            return (
                empty_cache(),
                obj.get("sha"),
                None,
            )

        content = base64.b64decode(
            encoded.replace("\n", "")
        ).decode("utf-8")

        data = json.loads(content)

        cache = normalize_cache(data)

        return (
            cache,
            obj.get("sha"),
            None,
        )

    except Exception as e:
        return (
            None,
            None,
            str(e),
        )


# ============================================================
# MESCLAGEM SEGURA DO CACHE
# ============================================================

def merge_caches(remote, local):
    """
    Mescla o cache remoto do GitHub com o cache local.

    O objetivo é NUNCA perder informações já persistidas.

    Estruturas importantes:

        date_searches
        fixtures
        details

    Em caso de conflito:
        - dados existentes no remoto são preservados;
        - dados novos do local são adicionados;
        - detalhes já existentes não são apagados.
    """

    remote = normalize_cache(remote)
    local = normalize_cache(local)

    merged = normalize_cache(remote)

    # --------------------------------------------------------
    # Contador de chamadas
    # --------------------------------------------------------

    merged["api_calls"] = max(
        int(remote.get("api_calls", 0)),
        int(local.get("api_calls", 0)),
    )

    # --------------------------------------------------------
    # Última chamada
    # --------------------------------------------------------

    remote_last = remote.get(
        "last_api_call"
    )

    local_last = local.get(
        "last_api_call"
    )

    if remote_last and local_last:
        if local_last > remote_last:
            merged["last_api_call"] = local_last
        else:
            merged["last_api_call"] = remote_last

    elif local_last:
        merged["last_api_call"] = local_last

    else:
        merged["last_api_call"] = remote_last

    # --------------------------------------------------------
    # BUSCAS POR DATA
    # --------------------------------------------------------

    remote_dates = remote.get(
        "date_searches",
        {},
    )

    local_dates = local.get(
        "date_searches",
        {},
    )

    merged_dates = dict(remote_dates)

    for key, value in local_dates.items():

        # Se ainda não existe, adiciona.
        if key not in merged_dates:
            merged_dates[key] = value

        # Se local possui dados e remoto está vazio,
        # mantém os dados locais.
        elif (
            not merged_dates[key]
            and value
        ):
            merged_dates[key] = value

    merged["date_searches"] = merged_dates

    # --------------------------------------------------------
    # ÍNDICE DE FIXTURES
    # --------------------------------------------------------

    remote_fixtures = remote.get(
        "fixtures",
        {},
    )

    local_fixtures = local.get(
        "fixtures",
        {},
    )

    merged_fixtures = dict(
        remote_fixtures
    )

    for key, value in local_fixtures.items():

        if key not in merged_fixtures:
            merged_fixtures[key] = value

        elif (
            not merged_fixtures[key]
            and value
        ):
            merged_fixtures[key] = value

    merged["fixtures"] = merged_fixtures

    # --------------------------------------------------------
    # DETALHES / ENRIQUECIMENTOS
    # --------------------------------------------------------

    remote_details = remote.get(
        "details",
        {},
    )

    local_details = local.get(
        "details",
        {},
    )

    merged_details = dict(
        remote_details
    )

    for key, value in local_details.items():

        # Novo enriquecimento.
        if key not in merged_details:
            merged_details[key] = value
            continue

        # Nunca substituir um enriquecimento existente
        # por None ou estrutura vazia.
        if value is None:
            continue

        if not merged_details[key]:
            merged_details[key] = value

    merged["details"] = merged_details

    return merged


# ============================================================
# GITHUB — GRAVAÇÃO SEGURA
# ============================================================

def github_save_cache(cache):
    """
    Salva o cache de forma segura.

    Antes de gravar:

    1. lê novamente o arquivo atual do GitHub;
    2. mescla remoto + local;
    3. usa o SHA mais recente;
    4. grava o resultado.

    Isso impede que uma operação baseada em cache antigo
    apague enriquecimentos já persistidos.
    """

    if not GITHUB_TOKEN:
        return False, (
            "GITHUB_TOKEN não configurado."
        )

    # --------------------------------------------------------
    # PRIMEIRA LEITURA FRESCA
    # --------------------------------------------------------

    remote_cache, remote_sha, error = (
        github_load_cache()
    )

    if error:
        return False, (
            "Não foi possível ler o cache atual "
            f"antes de gravar: {error}"
        )

    # --------------------------------------------------------
    # MESCLA
    # --------------------------------------------------------

    merged_cache = merge_caches(
        remote_cache,
        cache,
    )

    try:

        content = json.dumps(
            merged_cache,
            ensure_ascii=False,
            indent=2,
        )

        encoded = base64.b64encode(
            content.encode("utf-8")
        ).decode("ascii")

        payload = {
            "message": (
                "Atualiza cache persistente da API-Sports"
            ),
            "content": encoded,
            "branch": GITHUB_BRANCH,
        }

        if remote_sha:
            payload["sha"] = remote_sha

        response = requests.put(
            github_file_url(),
            headers=github_headers(),
            json=payload,
            timeout=20,
        )

        # ----------------------------------------------------
        # CONFLITO
        # ----------------------------------------------------

        if response.status_code == 409:

            # Outra execução gravou entre o GET e o PUT.
            # Fazemos uma nova leitura e tentamos novamente.

            fresh_cache, fresh_sha, fresh_error = (
                github_load_cache()
            )

            if fresh_error:
                return False, (
                    "Conflito no GitHub e não foi possível "
                    f"reler o cache: {fresh_error}"
                )

            merged_cache = merge_caches(
                fresh_cache,
                cache,
            )

            content = json.dumps(
                merged_cache,
                ensure_ascii=False,
                indent=2,
            )

            encoded = base64.b64encode(
                content.encode("utf-8")
            ).decode("ascii")

            retry_payload = {
                "message": (
                    "Atualiza cache persistente da API-Sports"
                ),
                "content": encoded,
                "branch": GITHUB_BRANCH,
            }

            if fresh_sha:
                retry_payload["sha"] = fresh_sha

            response = requests.put(
                github_file_url(),
                headers=github_headers(),
                json=retry_payload,
                timeout=20,
            )

        if not response.ok:
            return False, (
                f"GitHub PUT {response.status_code}: "
                f"{response.text[:500]}"
            )

        return True, None

    except Exception as e:
        return False, str(e)


# ============================================================
# API-SPORTS
# ============================================================

def api_get(endpoint, params):
    """
    ÚNICO ponto do aplicativo que pode chamar
    a API-Sports.
    """

    if not API_KEY:
        return (
            None,
            "API-Sports key não configurada.",
        )

    headers = {
        "x-apisports-key": API_KEY
    }

    try:

        response = requests.get(
            f"{BASE_API}/{endpoint}",
            headers=headers,
            params=params,
            timeout=30,
        )

        try:
            payload = response.json()

        except Exception:
            payload = {
                "errors": {
                    "http": response.status_code,
                    "text": response.text[:500],
                }
            }

        if not response.ok:
            return None, payload

        return payload, None

    except Exception as e:
        return None, str(e)


# ============================================================
# CONTROLE DE CHAMADAS
# ============================================================

def register_api_call(cache):
    cache["api_calls"] = (
        int(
            cache.get(
                "api_calls",
                0,
            )
        )
        + 1
    )

    cache["last_api_call"] = (
        datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


# ============================================================
# BUSCA DE PARTIDAS POR DATA
# ============================================================

def search_fixtures(
    cache,
    selected_date,
):
    """
    Procura primeiro no cache persistente.

    Se a data existir:
        NÃO chama API-Sports.

    Se não existir:
        faz UMA chamada à API-Sports
        e salva de forma segura.
    """

    key = selected_date.isoformat()

    cached = (
        cache
        .get("date_searches", {})
        .get(key)
    )

    if cached is not None:
        return (
            cached,
            False,
            None,
        )

    payload, error = api_get(
        "fixtures",
        {
            "date": key
        },
    )

    if error:
        return (
            None,
            True,
            error,
        )

    response = payload.get(
        "response",
        [],
    )

    register_api_call(cache)

    cache.setdefault(
        "date_searches",
        {},
    )[key] = response

    # --------------------------------------------------------
    # INDEXA FIXTURES
    # --------------------------------------------------------

    for item in response:

        fixture = item.get(
            "fixture",
            {},
        )

        fixture_id = fixture.get(
            "id"
        )

        if fixture_id:

            cache.setdefault(
                "fixtures",
                {},
            )[str(fixture_id)] = item

    # --------------------------------------------------------
    # PERSISTÊNCIA SEGURA
    # --------------------------------------------------------

    ok, save_error = (
        github_save_cache(cache)
    )

    if not ok:
        return (
            response,
            True,
            save_error,
        )

    return (
        response,
        True,
        None,
    )


# ============================================================
# ENRIQUECIMENTO DE UMA PARTIDA
# ============================================================

def enrich_fixture(
    cache,
    fixture_id,
):
    """
    Procura primeiro no cache persistente.

    Se já houver details:
        NÃO chama API-Sports.

    Se não houver:
        faz UMA chamada /fixtures?id=...
        e salva de forma segura.
    """

    key = str(fixture_id)

    existing = (
        cache
        .get("details", {})
        .get(key)
    )

    if existing is not None:
        return (
            existing,
            False,
            None,
        )

    payload, error = api_get(
        "fixtures",
        {
            "id": fixture_id
        },
    )

    if error:
        return (
            None,
            True,
            error,
        )

    response = payload.get(
        "response",
        [],
    )

    register_api_call(cache)

    if not response:

        cache.setdefault(
            "details",
            {},
        )[key] = {
            "response": [],
            "errors": payload.get(
                "errors",
                {},
            ),
            "empty": True,
        }

    else:

        cache.setdefault(
            "details",
            {},
        )[key] = {
            "response": response,
            "errors": payload.get(
                "errors",
                {},
            ),
            "empty": False,
        }

    # --------------------------------------------------------
    # PERSISTÊNCIA SEGURA
    # --------------------------------------------------------

    ok, save_error = (
        github_save_cache(cache)
    )

    if not ok:
        return (
            cache["details"][key],
            True,
            save_error,
        )

    return (
        cache["details"][key],
        True,
        None,
    )


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


cache, cache_sha, cache_error = (
    github_load_cache()
)

if cache_error:

    st.error(
        f"Erro ao ler o cache do GitHub: "
        f"{cache_error}"
    )

    st.stop()


# ============================================================
# INTERFACE
# ============================================================

st.title(
    "🟣 Teste limpo — API-SPORTS"
)

st.caption(
    "Protótipo independente para diagnosticar "
    "descoberta, enriquecimento e persistência."
)


# ============================================================
# CONTROLE INTERNO
# ============================================================

st.subheader(
    "📊 Controle interno do teste"
)

c1, c2, c3 = st.columns(3)

with c1:

    st.metric(
        "Chamadas API-Sports registradas pelo app",
        cache.get(
            "api_calls",
            0,
        ),
    )


with c2:

    st.metric(
        "Datas armazenadas",
        len(
            cache.get(
                "date_searches",
                {},
            )
        ),
    )


with c3:

    st.metric(
        "Partidas enriquecidas",
        len(
            cache.get(
                "details",
                {},
            )
        ),
    )


if cache.get(
    "last_api_call"
):

    st.caption(
        "Última chamada registrada pelo app: "
        f"{cache['last_api_call']}"
    )


# ============================================================
# BUSCAR PARTIDAS
# ============================================================

st.subheader(
    "1️⃣ Buscar partidas"
)

selected_date = st.date_input(
    "Data",
    value=date.today(),
)


if st.button(
    "🔎 Buscar partidas desta data",
    type="primary",
):

    # --------------------------------------------------------
    # NOVA LEITURA DO GITHUB
    # --------------------------------------------------------

    cache, cache_sha, cache_error = (
        github_load_cache()
    )

    if cache_error:

        st.error(cache_error)
        st.stop()

    with st.spinner(
        "Consultando cache/API..."
    ):

        (
            fixtures,
            api_was_called,
            error,
        ) = search_fixtures(
            cache,
            selected_date,
        )

    if error:

        st.error(
            str(error)
        )

    elif fixtures is None:

        st.error(
            "Não foi possível obter as partidas."
        )

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

        st.session_state[
            "fixtures"
        ] = fixtures

        st.session_state[
            "selected_date"
        ] = selected_date.isoformat()


# ============================================================
# SELEÇÃO DA PARTIDA
# ============================================================

fixtures = st.session_state.get(
    "fixtures",
    [],
)


if fixtures:

    st.subheader(
        "2️⃣ Selecionar partida"
    )

    options = []

    for item in fixtures:

        fixture = item.get(
            "fixture",
            {},
        )

        league = item.get(
            "league",
            {},
        )

        teams = item.get(
            "teams",
            {},
        )

        fixture_id = fixture.get(
            "id"
        )

        home = (
            teams
            .get("home", {})
            .get(
                "name",
                "Casa",
            )
        )

        away = (
            teams
            .get("away", {})
            .get(
                "name",
                "Fora",
            )
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
            (
                label,
                fixture_id,
            )
        )

    labels = [
        item[0]
        for item in options
    ]

    selected_label = st.selectbox(
        "Partida",
        labels,
    )

    selected_fixture_id = dict(
        options
    )[selected_label]

    st.info(
        "Fixture identificado: "
        f"{selected_fixture_id}"
    )

    # --------------------------------------------------------
    # IMPORTANTE:
    # RECARREGA O CACHE PARA SABER SE O DETALHE JÁ EXISTE
    # --------------------------------------------------------

    fresh_cache, fresh_sha, fresh_error = (
        github_load_cache()
    )

    if fresh_error:

        st.error(
            fresh_error
        )
        st.stop()

    cache = fresh_cache

    cached_detail = (
        cache
        .get("details", {})
        .get(
            str(selected_fixture_id)
        )
    )

    if cached_detail is not None:

        if cached_detail.get(
            "empty"
        ):

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

            # ------------------------------------------------
            # ÚLTIMA LEITURA ANTES DE GASTAR API
            # ------------------------------------------------

            cache, cache_sha, cache_error = (
                github_load_cache()
            )

            if cache_error:

                st.error(
                    cache_error
                )
                st.stop()

            # ------------------------------------------------
            # SEGUNDA PROTEÇÃO:
            # verifica novamente se alguém já enriqueceu
            # essa partida.
            # ------------------------------------------------

            already_exists = (
                cache
                .get("details", {})
                .get(
                    str(selected_fixture_id)
                )
            )

            if already_exists is not None:

                st.success(
                    "🟢 A partida já estava enriquecida "
                    "no cache persistente. "
                    "Nenhuma chamada à API-Sports foi feita."
                )

                st.rerun()

            with st.spinner(
                "Verificando cache e API-Sports..."
            ):

                (
                    details,
                    api_was_called,
                    error,
                ) = enrich_fixture(
                    cache,
                    selected_fixture_id,
                )

            if error:

                st.error(
                    str(error)
                )

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

with st.expander(
    "🔎 Diagnóstico"
):

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
        "O contador registra somente chamadas "
        "à API-Sports feitas pelo próprio app."
    )

    st.write(
        "O consumo total da conta API-Sports "
        "é controlado separadamente pela própria API."
    )

    st.write(
        "O cache persistente fica em "
        f"`{GITHUB_FILE}`."
    )

    st.write(
        "O aplicativo nunca deve substituir um cache "
        "existente por um cache vazio devido a erro de leitura."
    )

    st.write(
        "Antes de cada gravação, o aplicativo relê "
        "o cache atual do GitHub e mescla os dados."
    )

    st.write(
        "Se uma data já estiver em `date_searches`, "
        "uma nova busca para essa data não deve gerar "
        "chamada à API-Sports."
    )

    st.write(
        "Se uma partida já estiver em `details`, "
        "o enriquecimento não deve gerar nova chamada."
    )
