import base64
import json
from datetime import date, datetime, timezone, timedelta
from zoneinfo import ZoneInfo

import requests
import streamlit as st


# ============================================================
# CONFIGURAÇÃO
# ============================================================

st.set_page_config(
    page_title="Teste limpo — API-SPORTS v13",
    page_icon="🟣",
    layout="wide",
)

BASE_API = "https://v3.football.api-sports.io"

# ============================================================
# FUSO HORÁRIO OFICIAL DO APLICATIVO
# ============================================================
# A API-Sports normalmente trabalha com timestamps ISO-8601/UTC.
# Toda exibição e toda referência de "hoje" no app passam pelo
# horário oficial de Manaus.
APP_TIMEZONE_NAME = "America/Manaus"
APP_TIMEZONE = ZoneInfo(APP_TIMEZONE_NAME)
APP_TIMEZONE_LABEL = "🇧🇷 Manaus (AM) — UTC-4"

GITHUB_OWNER = "jandersonnmelo-arch"
GITHUB_REPO = "Teste"
GITHUB_BRANCH = "main"

GITHUB_FILE = "dados_app/cache.json"

# Secrets usados pela API-Sports e pela persistência no GitHub.
# Mantemos os dois nomes aceitos para a chave da API para não quebrar
# a configuração que já estava funcionando no app.
API_KEY = (
    st.secrets.get("API_SPORTS_KEY")
    or st.secrets.get("API_FOOTBALL_KEY")
    or ""
)

GITHUB_TOKEN = st.secrets.get("GITHUB_TOKEN", "")


# ============================================================
# CAMPEONATOS PRÉ-SELECIONADOS
# ============================================================
# O filtro usa principalmente o ID da competição, porque a
# API-Sports pode devolver nomes oficiais diferentes dos nomes
# amigáveis mostrados na interface (ex.: "Serie B" em vez de
# "Brasileirão Série B").
ALLOWED_LEAGUE_IDS = {
    # Brasil
    71,   # Brasileirão Série A
    72,   # Brasileirão Série B
    73,   # Copa do Brasil

    # América do Sul
    13,   # CONMEBOL Libertadores
    11,   # CONMEBOL Sudamericana
    128,  # Liga Profesional Argentina

    # México
    262,  # Liga MX

    # Europa
    2,    # UEFA Champions League
    3,    # UEFA Europa League
    848,  # UEFA Conference League
    39,   # Premier League
    40,   # Championship
    140,  # La Liga
    78,   # Bundesliga
    61,   # Ligue 1
    135,  # Serie A (Itália)
    88,   # Eredivisie
    94,   # Primeira Liga

    # Seleções
    9,    # Copa América
    1,    # Copa do Mundo
}

# Nomes são mantidos como fallback caso algum item não traga
# o ID esperado no payload.
ALLOWED_LEAGUE_NAMES = {
    "Brasileirão Série A",
    "Brasileirão Série B",
    "Copa do Brasil",
    "Copa Libertadores",
    "Copa Sul-Americana",
    "CONMEBOL Libertadores",
    "CONMEBOL Sudamericana",
    "UEFA Champions League",
    "UEFA Europa League",
    "UEFA Conference League",
    "Premier League",
    "Championship",
    "La Liga",
    "Bundesliga",
    "Ligue 1",
    "Serie A",
    "Serie B",
    "Eredivisie",
    "Primeira Liga",
    "Liga Profesional Argentina",
    "Liga Profesional de Fútbol",
    "Primera División",
    "Primera Division",
    "Liga MX",
    "Liga BBVA MX",
    "Copa América",
    "Copa America",
    "Copa do Mundo",
    "World Cup",
}

# ============================================================
# DATA / HORA — MANAUS
# ============================================================

def now_local():
    """Retorna o instante atual no horário oficial de Manaus."""
    return datetime.now(APP_TIMEZONE)


def local_today():
    """Data de hoje segundo o horário de Manaus."""
    return now_local().date()


def parse_fixture_datetime(value):
    """
    Converte o timestamp da API-Sports para datetime consciente
    e normalizado no fuso de Manaus.

    Exemplos aceitos:
      2026-08-12T22:00:00+00:00
      2026-08-12T22:00:00Z
      timestamp sem timezone -> tratado como UTC
    """
    if not value:
        return None

    try:
        raw = str(value).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(APP_TIMEZONE)
    except (TypeError, ValueError, OverflowError):
        return None


def format_fixture_local_datetime(value):
    """Exibe a data/hora da partida no padrão brasileiro de Manaus."""
    dt = parse_fixture_datetime(value)
    if not dt:
        return "Data/hora indisponível"

    return dt.strftime("%d/%m/%Y %H:%M")


def fixture_local_date(value):
    """Retorna a data local da partida em Manaus."""
    dt = parse_fixture_datetime(value)
    return dt.date() if dt else None


def fixture_status_info(fixture):
    """
    Produz um status amigável baseado no horário local e no status
    oficial retornado pela API-Sports.
    """
    if not isinstance(fixture, dict):
        return {
            "code": "",
            "label": "Status indisponível",
            "kind": "unknown",
            "local_dt": None,
        }

    local_dt = parse_fixture_datetime(fixture.get("date"))
    status = fixture.get("status") or {}
    code = str(status.get("short") or "").upper()
    elapsed = status.get("elapsed")

    finished_codes = {"FT", "AET", "PEN"}
    live_codes = {"1H", "HT", "2H", "ET", "BT", "P", "LIVE", "INT", "SUSP"}
    postponed_codes = {"PST"}
    cancelled_codes = {"CANC", "ABD", "AWD", "WO"}

    if code in finished_codes:
        return {
            "code": code,
            "label": "✅ FINALIZADO",
            "kind": "finished",
            "local_dt": local_dt,
        }

    if code in cancelled_codes:
        return {
            "code": code,
            "label": "⛔ CANCELADO/ENCERRADO",
            "kind": "cancelled",
            "local_dt": local_dt,
        }

    if code in postponed_codes:
        return {
            "code": code,
            "label": "⏸️ ADIADO",
            "kind": "postponed",
            "local_dt": local_dt,
        }

    # Para jogos ao vivo, a API é a autoridade principal.
    if code in live_codes:
        minute_text = f" — {elapsed}'" if elapsed is not None else ""
        return {
            "code": code,
            "label": f"🟢 AO VIVO{minute_text}",
            "kind": "live",
            "local_dt": local_dt,
        }

    # Fallback temporal para partidas futuras sem status reconhecido.
    now = now_local()

    if local_dt:
        if local_dt <= now:
            return {
                "code": code,
                "label": "🟢 AO VIVO / EM ANDAMENTO",
                "kind": "live",
                "local_dt": local_dt,
            }

        delta = local_dt - now
        total_minutes = max(0, int(delta.total_seconds() // 60))

        if local_dt.date() == now.date():
            if total_minutes < 60:
                label = f"🟡 COMEÇA EM {total_minutes} MIN"
            else:
                hours = total_minutes // 60
                minutes = total_minutes % 60
                if minutes:
                    label = f"🔵 HOJE — EM {hours}H{minutes:02d}"
                else:
                    label = f"🔵 HOJE — EM {hours}H"

            return {
                "code": code,
                "label": label,
                "kind": "today",
                "local_dt": local_dt,
            }

        tomorrow = now.date() + timedelta(days=1)
        if local_dt.date() == tomorrow:
            return {
                "code": code,
                "label": f"📅 AMANHÃ — {local_dt.strftime('%H:%M')}",
                "kind": "tomorrow",
                "local_dt": local_dt,
            }

        return {
            "code": code,
            "label": f"📆 {local_dt.strftime('%d/%m/%Y')} — {local_dt.strftime('%H:%M')}",
            "kind": "future",
            "local_dt": local_dt,
        }

    return {
        "code": code,
        "label": "⚪ HORÁRIO INDISPONÍVEL",
        "kind": "unknown",
        "local_dt": None,
    }


def fixture_score_text(item):
    """Monta o placar atual/final quando a API-Sports o disponibiliza."""
    score = item.get("score") or {}
    goals = item.get("goals") or {}

    home = goals.get("home")
    away = goals.get("away")

    if home is None:
        home = score.get("fulltime", {}).get("home")
    if away is None:
        away = score.get("fulltime", {}).get("away")

    if home is None or away is None:
        return ""

    return f"{home} x {away}"


def fixture_display_label(item):
    """
    Label compacto e legível para celular.
    Mostra campeonato + confronto + horário de Manaus + status.
    """
    fixture = item.get("fixture") or {}
    league = item.get("league") or {}
    teams = item.get("teams") or {}

    fixture_id = fixture.get("id")
    home = (teams.get("home") or {}).get("name", "Casa")
    away = (teams.get("away") or {}).get("name", "Fora")
    league_name = league.get("name", "Competição desconhecida")

    local_dt = parse_fixture_datetime(fixture.get("date"))
    status_info = fixture_status_info(fixture)
    score = fixture_score_text(item)

    time_text = local_dt.strftime("%H:%M") if local_dt else "--:--"
    score_text = f" • ⚽ {score}" if score else ""

    return (
        f"🏆 {league_name}  |  ⚽ {home} x {away}  |  "
        f"🕒 {time_text}  |  {status_info['label']}{score_text}"
    )


def fixture_short_label(item):
    """Versão ainda mais curta para a lista de seleção."""
    fixture = item.get("fixture") or {}
    league = item.get("league") or {}
    teams = item.get("teams") or {}

    home = (teams.get("home") or {}).get("name", "Casa")
    away = (teams.get("away") or {}).get("name", "Fora")
    league_name = league.get("name", "Competição desconhecida")

    local_dt = parse_fixture_datetime(fixture.get("date"))
    status_info = fixture_status_info(fixture)
    score = fixture_score_text(item)

    time_text = local_dt.strftime("%H:%M") if local_dt else "--:--"
    score_text = f" • ⚽ {score}" if score else ""

    return (
        f"🏆 {league_name}  •  {home} x {away}  •  "
        f"{time_text}  •  {status_info['label']}{score_text}"
    )

def league_is_allowed(league):
    """Retorna True somente para campeonatos previamente autorizados."""
    if not isinstance(league, dict):
        return False

    league_id = league.get("id")
    if league_id is not None:
        try:
            if int(league_id) in ALLOWED_LEAGUE_IDS:
                return True
        except (TypeError, ValueError):
            pass

    league_name = str(league.get("name", "")).strip()
    return league_name in ALLOWED_LEAGUE_NAMES


def filter_allowed_fixtures(fixtures):
    """
    Remove localmente partidas de campeonatos não autorizados.

    Não faz nenhuma chamada à API-Sports. O cache continua podendo
    armazenar a resposta original; o filtro é aplicado na interface.
    """
    return [
        item
        for item in (fixtures or [])
        if league_is_allowed(item.get("league", {}))
    ]

# ============================================================
# CACHE PADRÃO
# ============================================================

def empty_cache():
    return {
        "version": 5,
        "api_calls": 0,
        "last_api_call": None,
        "quota": {
            "daily_used": None,
            "daily_limit": None,
            "daily_remaining": None,
            "minute_limit": None,
            "minute_remaining": None,
            "updated_at": None,
        },
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

    if isinstance(data.get("quota"), dict):
        quota = data["quota"]
        for key in (
            "daily_used",
            "daily_limit",
            "daily_remaining",
            "minute_limit",
            "minute_remaining",
            "updated_at",
        ):
            cache["quota"][key] = quota.get(key)

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

def github_cache_diagnostic(cache, sha, error):
    """
    Produz um diagnóstico local da persistência sem fazer nenhuma
    chamada adicional ao GitHub ou à API-Sports.
    """
    details = (
        (cache or {}).get("details", {})
        if isinstance(cache, dict)
        else {}
    )
    fixtures = (
        (cache or {}).get("fixtures", {})
        if isinstance(cache, dict)
        else {}
    )
    quota = (
        (cache or {}).get("quota", {})
        if isinstance(cache, dict)
        else {}
    )

    fixture_1607648 = details.get("1607648")
    return {
        "owner": GITHUB_OWNER,
        "repo": GITHUB_REPO,
        "branch": GITHUB_BRANCH,
        "file": GITHUB_FILE,
        "cache_loaded": isinstance(cache, dict),
        "sha": sha,
        "error": error,
        "api_calls_internal": (
            (cache or {}).get("api_calls")
            if isinstance(cache, dict)
            else None
        ),
        "daily_used": quota.get("daily_used"),
        "daily_remaining": quota.get("daily_remaining"),
        "daily_limit": quota.get("daily_limit"),
        "dates": len(
            (cache or {}).get("date_searches", {})
            if isinstance(cache, dict)
            else {}
        ),
        "fixtures": len(fixtures),
        "details": len(details),
        "fixture_1607648": (
            "ENCONTRADO" if fixture_1607648 is not None
            else "NÃO ENCONTRADO"
        ),
        "fixture_1607648_empty": (
            fixture_1607648.get("empty")
            if isinstance(fixture_1607648, dict)
            else None
        ),
    }


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

        # 404 é tratado como erro explícito.
        # Em repositórios privados, GitHub pode devolver 404 quando
        # o token não possui acesso ao repositório/arquivo. Portanto,
        # nunca podemos interpretar 404 como "cache vazio".
        if response.status_code == 404:
            return (
                None,
                None,
                (
                    "GitHub GET 404: cache.json não foi encontrado "
                    "ou o GITHUB_TOKEN não tem acesso ao repositório. "
                    f"URL: {github_file_url()} | branch: {GITHUB_BRANCH} | "
                    f"arquivo: {GITHUB_FILE}"
                ),
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
                None,
                obj.get("sha"),
                "GitHub retornou o arquivo sem conteúdo/base64.",
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



def github_commits_url():
    return (
        f"https://api.github.com/repos/"
        f"{GITHUB_OWNER}/{GITHUB_REPO}/commits"
    )


def github_load_cache_at_commit(commit_sha):
    """
    Lê uma versão histórica do cache.json em um commit específico.
    Isso serve somente para RECUPERAÇÃO; não chama a API-Sports.
    """
    if not GITHUB_TOKEN:
        return None, None, "GITHUB_TOKEN não configurado."

    try:
        response = requests.get(
            github_file_url(),
            headers=github_headers(),
            params={"ref": commit_sha},
            timeout=20,
        )

        if response.status_code == 404:
            return None, None, None

        if not response.ok:
            return (
                None,
                None,
                f"GitHub histórico GET {response.status_code}: "
                f"{response.text[:500]}",
            )

        obj = response.json()
        encoded = obj.get("content", "")

        if not encoded:
            return None, obj.get("sha"), None

        content = base64.b64decode(
            encoded.replace("\n", "")
        ).decode("utf-8")

        return normalize_cache(json.loads(content)), obj.get("sha"), None

    except Exception as e:
        return None, None, str(e)


def github_find_historical_detail(fixture_id, max_commits=20):
    """
    Procura uma versão anterior do cache.json que contenha o
    enriquecimento da partida.

    Importante:
    - usa somente a API do GitHub;
    - NÃO consome chamadas da API-Sports;
    - não altera nada até o usuário mandar recuperar.
    """
    if not GITHUB_TOKEN:
        return None, "GITHUB_TOKEN não configurado."

    key = str(fixture_id)

    try:
        response = requests.get(
            github_commits_url(),
            headers=github_headers(),
            params={
                "path": GITHUB_FILE,
                "sha": GITHUB_BRANCH,
                "per_page": max_commits,
            },
            timeout=20,
        )

        if not response.ok:
            return (
                None,
                f"GitHub commits {response.status_code}: "
                f"{response.text[:500]}",
            )

        commits = response.json()

        for commit in commits:
            commit_sha = commit.get("sha")
            if not commit_sha:
                continue

            historical_cache, _, error = (
                github_load_cache_at_commit(commit_sha)
            )

            if error:
                continue

            if not historical_cache:
                continue

            historical_detail = (
                historical_cache
                .get("details", {})
                .get(key)
            )

            if historical_detail:
                return {
                    "detail": historical_detail,
                    "commit": commit_sha,
                    "date": (
                        commit.get("commit", {})
                        .get("author", {})
                        .get("date")
                    ),
                }, None

        return None, None

    except Exception as e:
        return None, str(e)


def restore_historical_detail(cache, fixture_id, historical):
    """
    Restaura um enriquecimento encontrado no histórico do GitHub.

    A restauração é feita sobre uma leitura FRESCA do GitHub para
    evitar que um cache antigo sobrescreva ou esconda o detalhe
    histórico.

    Não chama a API-Sports.
    """
    key = str(fixture_id)

    if not historical or not historical.get("detail"):
        return False

    historical_detail = historical["detail"]

    # --------------------------------------------------------
    # 1. Leitura fresca do GitHub
    # --------------------------------------------------------
    fresh_cache, _, fresh_error = github_load_cache()

    if fresh_error:
        return False, fresh_error

    if fresh_cache is None:
        return False, "Não foi possível carregar o cache atual do GitHub."

    # --------------------------------------------------------
    # 2. Injeta o detalhe diretamente no cache mais recente.
    # --------------------------------------------------------
    fresh_cache = normalize_cache(fresh_cache)
    fresh_cache.setdefault("details", {})[key] = historical_detail

    # --------------------------------------------------------
    # 3. Grava usando a proteção normal de merge/conflito.
    # --------------------------------------------------------
    ok, save_error = github_save_cache(fresh_cache)

    if not ok:
        return False, save_error

    # --------------------------------------------------------
    # 4. Confirma imediatamente no GitHub.
    # --------------------------------------------------------
    verified_cache, _, verify_error = github_load_cache()

    if verify_error:
        return False, (
            "A restauração foi enviada, mas não foi possível "
            f"confirmar a leitura do GitHub: {verify_error}"
        )

    verified_detail = (
        verified_cache
        .get("details", {})
        .get(key)
        if verified_cache
        else None
    )

    if verified_detail is None:
        return False, (
            "A gravação retornou sucesso, mas o detalhe "
            f"do fixture {key} não apareceu no cache do GitHub."
        )

    return True


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
    # QUOTA REAL DA API
    # --------------------------------------------------------

    remote_quota = remote.get("quota", {})
    local_quota = local.get("quota", {})

    merged_quota = dict(remote_quota)

    # O snapshot local de quota vem da resposta mais recente
    # da API-Sports. Se existir, ele é mais novo que o remoto
    # somente quando possui updated_at mais recente.
    remote_updated = remote_quota.get("updated_at")
    local_updated = local_quota.get("updated_at")

    if local_updated and (
        not remote_updated or local_updated >= remote_updated
    ):
        merged_quota.update(local_quota)

    merged["quota"] = merged_quota

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

def parse_int_header(value):
    """
    Converte headers de rate limit em inteiro sem quebrar
    se o provedor devolver valor ausente ou inesperado.
    """
    if value is None:
        return None

    try:
        return int(str(value).split(",")[0].strip())
    except (TypeError, ValueError):
        return None


def update_real_quota_from_response(cache, response):
    """
    Guarda no cache os headers reais devolvidos pela API-Sports.

    Esses valores são os mais confiáveis para o consumo real:
      - x-ratelimit-requests-limit: limite diário
      - x-ratelimit-requests-remaining: restante diário
      - X-RateLimit-Limit: limite por minuto
      - X-RateLimit-Remaining: restante por minuto
    """
    daily_limit = parse_int_header(
        response.headers.get("x-ratelimit-requests-limit")
    )
    daily_remaining = parse_int_header(
        response.headers.get("x-ratelimit-requests-remaining")
    )
    minute_limit = parse_int_header(
        response.headers.get("X-RateLimit-Limit")
        or response.headers.get("x-ratelimit-limit")
    )
    minute_remaining = parse_int_header(
        response.headers.get("X-RateLimit-Remaining")
        or response.headers.get("x-ratelimit-remaining")
    )

    quota = cache.setdefault("quota", {})

    if daily_limit is not None:
        quota["daily_limit"] = daily_limit

    if daily_remaining is not None:
        quota["daily_remaining"] = daily_remaining

    if daily_limit is not None and daily_remaining is not None:
        quota["daily_used"] = max(
            0,
            daily_limit - daily_remaining,
        )

    if minute_limit is not None:
        quota["minute_limit"] = minute_limit

    if minute_remaining is not None:
        quota["minute_remaining"] = minute_remaining

    quota["updated_at"] = (
        datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def api_get(endpoint, params, cache=None):
    """
    ÚNICO ponto do aplicativo que pode chamar
    a API-Sports.

    Além do payload, captura os headers reais de
    rate limit devolvidos pela API.
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

        if cache is not None:
            update_real_quota_from_response(
                cache,
                response,
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


def api_status(cache):
    """
    Consulta o endpoint /status.

    Segundo a documentação oficial da API-FOOTBALL,
    esta chamada não consome a cota diária.
    Ela informa o uso atual e o limite diário da conta.
    """
    if not API_KEY:
        return None, "API-Sports key não configurada."

    try:
        response = requests.get(
            f"{BASE_API}/status",
            headers={
                "x-apisports-key": API_KEY
            },
            timeout=20,
        )

        try:
            payload = response.json()
        except Exception:
            payload = {}

        if not response.ok:
            return None, payload

        account = (
            payload
            .get("response", {})
            .get("requests", {})
        )

        current = account.get("current")
        limit_day = account.get("limit_day")

        quota = cache.setdefault("quota", {})

        if current is not None:
            quota["daily_used"] = int(current)

        if limit_day is not None:
            quota["daily_limit"] = int(limit_day)

        if (
            quota.get("daily_limit") is not None
            and quota.get("daily_used") is not None
        ):
            quota["daily_remaining"] = max(
                0,
                quota["daily_limit"] - quota["daily_used"],
            )

        quota["updated_at"] = (
            datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )

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

    # A chave inclui o fuso para impedir que um resultado obtido
    # em outro timezone seja reutilizado como se fosse Manaus.
    key = f"{selected_date.isoformat()}|{APP_TIMEZONE_NAME}"

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
            "date": selected_date.isoformat(),
            "timezone": APP_TIMEZONE_NAME,
        },
        cache=cache,
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
        cache=cache,
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

github_diag = github_cache_diagnostic(
    cache,
    cache_sha,
    cache_error,
)

if cache_error:

    st.error(
        f"Erro ao ler o cache do GitHub: "
        f"{cache_error}"
    )

    st.stop()


# IMPORTANTE:
# A consulta /status NÃO é executada automaticamente a cada rerun.
# Isso evita uma requisição extra sempre que o usuário troca de
# partida, restaura histórico ou o Streamlit reexecuta a página.
#
# O consumo real continua disponível no botão:
# "🔄 Atualizar consumo real".
#
# Os valores exibidos inicialmente são o último snapshot persistido.
if "quota_status_loaded" not in st.session_state:
    st.session_state["quota_status_loaded"] = False


# ============================================================
# ESTADO DA INTERFACE
# ============================================================

# O Streamlit reexecuta o script a cada clique. O resultado da
# busca histórica precisa sobreviver ao rerun do clique em
# "Restaurar".
if "historical_detail" not in st.session_state:
    st.session_state["historical_detail"] = None

if "historical_fixture_id" not in st.session_state:
    st.session_state["historical_fixture_id"] = None


# ============================================================
# INTERFACE
# ============================================================

st.title(
    "🟣 Teste limpo — API-SPORTS v13"
)

st.caption(
    "Protótipo independente para diagnosticar descoberta, "
    "enriquecimento, persistência e leitura do GitHub."
)

st.info(
    f"🕐 **Horário oficial do aplicativo:** {APP_TIMEZONE_LABEL}  •  "
    f"**Agora:** {now_local().strftime('%d/%m/%Y %H:%M')}"
)


# ============================================================
# CONTROLE DE CONSUMO REAL
# ============================================================

st.subheader(
    "🟢 Consumo real da API-Sports"
)

st.caption(
    "Os valores abaixo mostram o último snapshot real salvo da conta. "
    "Para consultar o consumo atual da API-Sports, use "
    "🔄 Atualizar consumo real. O contador interno registra somente "
    "chamadas de dados feitas pelo próprio aplicativo."
)

quota = cache.get("quota", {})

daily_used = quota.get("daily_used")
daily_remaining = quota.get("daily_remaining")
daily_limit = quota.get("daily_limit")

minute_remaining = quota.get("minute_remaining")
minute_limit = quota.get("minute_limit")

q1, q2, q3 = st.columns(3)

with q1:
    st.metric(
        "Chamadas hoje",
        daily_used if daily_used is not None else "—",
    )

with q2:
    st.metric(
        "Restantes hoje",
        daily_remaining if daily_remaining is not None else "—",
    )

with q3:
    st.metric(
        "Limite diário",
        daily_limit if daily_limit is not None else "—",
    )

if (
    daily_used is not None
    and daily_limit
    and daily_limit > 0
):
    usage = min(
        1.0,
        max(
            0.0,
            daily_used / daily_limit,
        ),
    )
    st.progress(
        usage,
        text=f"Uso diário real: {usage * 100:.1f}%",
    )

if (
    minute_remaining is not None
    and minute_limit is not None
):
    st.caption(
        "Limite por minuto: "
        f"{minute_remaining} de {minute_limit} "
        "chamadas restantes."
    )
else:
    st.caption(
        "Limite por minuto: ainda será atualizado "
        "na próxima chamada real à API-Sports."
    )

if quota.get("updated_at"):
    quota_updated = quota["updated_at"]

    try:
        quota_dt = datetime.fromisoformat(
            str(quota_updated).replace("Z", "+00:00")
        ).astimezone(APP_TIMEZONE)

        quota_updated_display = quota_dt.strftime(
            "%d/%m/%Y %H:%M:%S"
        )
    except (TypeError, ValueError, OverflowError):
        quota_updated_display = str(quota_updated)

    st.caption(
        "Consumo real atualizado em: "
        f"{quota_updated_display} — Manaus (AM)"
    )

if st.button(
    "🔄 Atualizar consumo real",
    help="Consulta /status da API-Sports. A documentação informa que /status não consome a cota diária.",
):
    with st.spinner("Atualizando consumo real..."):
        _, status_error = api_status(cache)

    if status_error:
        st.error(
            f"Não foi possível atualizar o consumo: {status_error}"
        )
    else:
        ok, save_error = github_save_cache(cache)

        if not ok:
            st.warning(
                "O consumo foi consultado, mas o snapshot não pôde "
                f"ser salvo no GitHub: {save_error}"
            )
        else:
            st.session_state["quota_status_loaded"] = True
            st.rerun()

st.divider()

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

with st.expander("ℹ️ Estado do cache", expanded=False):

    st.write(
        "As métricas internas são lidas diretamente do "
        "cache persistente carregado do GitHub."
    )

    st.write(
        "O consumo real diário e por minuto vem dos "
        "limites informados pela própria API-Sports."
    )

    st.write(
        "Uma partida só conta como enriquecida quando existe "
        "um registro não vazio em `details`."
    )

    st.write(
        "Se o registro sumiu, o aplicativo tenta primeiro "
        "recuperá-lo do histórico do GitHub antes de oferecer "
        "uma nova chamada à API-Sports."
    )


# ============================================================
# DIAGNÓSTICO VISÍVEL DA PERSISTÊNCIA
# ============================================================

with st.expander(
    "🔗 Diagnóstico GitHub / cache",
    expanded=True,
):
    st.caption(
        "Leitura do cache persistente, sem fazer chamada extra "
        "à API-Sports."
    )

    d1, d2, d3 = st.columns(3)

    with d1:
        st.metric(
            "Cache carregado",
            "✅ SIM" if github_diag["cache_loaded"] else "❌ NÃO",
        )

    with d2:
        st.metric(
            "Details",
            github_diag["details"]
            if github_diag["details"] is not None
            else "—",
        )

    with d3:
        st.metric(
            "Fixture 1607648",
            github_diag["fixture_1607648"],
        )

    st.write(
        f"**Repositório:** `{github_diag['owner']}/{github_diag['repo']}`"
    )
    st.write(
        f"**Branch:** `{github_diag['branch']}`"
    )
    st.write(
        f"**Arquivo:** `{github_diag['file']}`"
    )

    if github_diag["sha"]:
        st.caption(
            f"SHA do arquivo carregado: `{github_diag['sha']}`"
        )

    if github_diag["cache_loaded"]:
        st.success(
            "O aplicativo carregou um cache válido do GitHub."
        )
        st.write(
            f"**Chamadas internas registradas:** "
            f"{github_diag['api_calls_internal']}"
        )
        st.write(
            f"**Consumo real persistido:** "
            f"{github_diag['daily_used']} / "
            f"{github_diag['daily_limit']} "
            f"(restantes: {github_diag['daily_remaining']})"
        )
        st.write(
            f"**Datas:** {github_diag['dates']}  •  "
            f"**Fixtures indexados:** {github_diag['fixtures']}  •  "
            f"**Enriquecimentos:** {github_diag['details']}"
        )

        if github_diag["fixture_1607648"] == "ENCONTRADO":
            st.success(
                "Fixture 1607648 encontrado no `details` do cache. "
                "O app deve reconhecer essa partida como já enriquecida."
            )
        else:
            st.info(
                "Fixture 1607648 não está no `details` do cache carregado."
            )
    else:
        st.error(
            "O aplicativo não conseguiu carregar um cache válido. "
            "Nenhuma gravação deve ser feita enquanto esse erro existir."
        )

    st.info(
        "Proteção ativa: HTTP 404 do GitHub não é mais interpretado "
        "como cache vazio."
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

st.caption(
    "🎯 Filtro ativo: somente campeonatos pré-acertados "
    "(incluindo Argentina e México)."
)

selected_date = st.date_input(
    "Data",
    value=local_today(),
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
                f"Encontradas {len(fixtures)} partidas nos "
                "campeonatos pré-selecionados. "
                "Esta operação consultou a API-Sports."
            )

        else:

            st.info(
                f"Encontradas {len(fixtures)} partidas nos "
                "campeonatos pré-selecionados a partir do CACHE — "
                "nenhuma chamada à API-Sports foi feita."
            )

        total_before_filter = st.session_state.get(
            "fixtures_total_found",
            len(fixtures),
        )
        allowed_after_filter = st.session_state.get(
            "fixtures_allowed_found",
            len(fixtures),
        )

        if total_before_filter != allowed_after_filter:
            st.caption(
                f"{total_before_filter - allowed_after_filter} "
                "partida(s) de outros campeonatos foram ocultadas "
                "pelo filtro pré-acertado."
            )

        # Filtra localmente para mostrar somente os campeonatos
        # previamente definidos. Isso não consome a API-Sports.
        allowed_fixtures = filter_allowed_fixtures(fixtures)

        st.session_state[
            "fixtures"
        ] = allowed_fixtures

        st.session_state[
            "fixtures_total_found"
        ] = len(fixtures)

        st.session_state[
            "fixtures_allowed_found"
        ] = len(allowed_fixtures)

        st.session_state[
            "selected_date"
        ] = selected_date.isoformat()

        st.session_state["historical_detail"] = None
        st.session_state["historical_fixture_id"] = None


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

    # --------------------------------------------------------
    # RESUMO RÁPIDO DA LISTA
    # --------------------------------------------------------

    league_groups = {}

    for item in fixtures:
        league = item.get("league") or {}
        league_name = league.get(
            "name",
            "Competição desconhecida",
        )
        league_groups.setdefault(
            league_name,
            []
        ).append(item)

    st.caption(
        f"📋 {len(fixtures)} partida(s) • "
        f"🏆 {len(league_groups)} campeonato(s) • "
        f"🕒 Horários em Manaus"
    )

    # --------------------------------------------------------
    # LISTA VISUAL AGRUPADA POR CAMPEONATO
    # --------------------------------------------------------
    # No celular fica muito mais fácil identificar primeiro o
    # campeonato e depois os jogos daquela competição.

    for league_name in sorted(league_groups):
        group = league_groups[league_name]

        with st.expander(
            f"🏆 {league_name} — {len(group)} jogo(s)",
            expanded=True,
        ):
            for item in group:
                fixture = item.get("fixture") or {}
                teams = item.get("teams") or {}

                fixture_id = fixture.get("id")
                home = (
                    teams.get("home") or {}
                ).get(
                    "name",
                    "Casa",
                )
                away = (
                    teams.get("away") or {}
                ).get(
                    "name",
                    "Fora",
                )

                local_dt = parse_fixture_datetime(
                    fixture.get("date")
                )
                status_info = fixture_status_info(
                    fixture
                )
                score = fixture_score_text(item)

                time_text = (
                    local_dt.strftime("%H:%M")
                    if local_dt
                    else "--:--"
                )

                score_text = (
                    f" • ⚽ {score}"
                    if score
                    else ""
                )

                st.markdown(
                    f"**⚽ {home} x {away}**  "
                    f"• 🕒 **{time_text}**  "
                    f"• {status_info['label']}"
                    f"{score_text}"
                )

    st.divider()

    # --------------------------------------------------------
    # SELETOR COMPACTO
    # --------------------------------------------------------
    # Mantemos o selectbox para preservar toda a lógica existente
    # de enriquecimento, cache e restauração, mas agora com um
    # label muito menor e muito mais legível.

    options = []

    for item in fixtures:
        fixture = item.get(
            "fixture",
            {},
        )

        fixture_id = fixture.get(
            "id"
        )

        options.append(
            (
                fixture_short_label(item),
                fixture_id,
            )
        )

    labels = [
        item[0]
        for item in options
    ]

    selected_label = st.selectbox(
        "Escolha o jogo para analisar",
        labels,
    )

    selected_fixture_id = dict(
        options
    )[selected_label]

    # Exibe a partida selecionada de forma limpa.
    selected_item = next(
        (
            item
            for item in fixtures
            if (
                item.get("fixture", {})
                .get("id")
                == selected_fixture_id
            )
        ),
        None,
    )

    if selected_item:
        selected_fixture = selected_item.get(
            "fixture",
            {}
        )
        selected_teams = selected_item.get(
            "teams",
            {}
        )
        selected_league = selected_item.get(
            "league",
            {}
        )

        selected_home = (
            selected_teams.get("home") or {}
        ).get(
            "name",
            "Casa",
        )
        selected_away = (
            selected_teams.get("away") or {}
        ).get(
            "name",
            "Fora",
        )

        selected_dt = parse_fixture_datetime(
            selected_fixture.get("date")
        )
        selected_status = fixture_status_info(
            selected_fixture
        )

        if selected_dt:
            selected_when = selected_dt.strftime(
                "%d/%m/%Y às %H:%M"
            )
        else:
            selected_when = "data/hora indisponível"

        st.success(
            f"🏆 **{selected_league.get('name', 'Competição desconhecida')}**\n\n"
            f"⚽ **{selected_home} x {selected_away}**\n\n"
            f"🕒 **{selected_when} — Manaus (AM)**\n\n"
            f"{selected_status['label']}  •  Fixture ID: {selected_fixture_id}"
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
            "neste cache."
        )

        st.caption(
            "O fixture está salvo, mas o registro em "
            "`details` não está presente no cache atual."
        )

        # ----------------------------------------------------
        # RECUPERAÇÃO DO HISTÓRICO
        # ----------------------------------------------------
        # NÃO aninhar o botão "Restaurar" dentro do botão "Procurar".
        # Em Streamlit, o clique em "Restaurar" causa um rerun e o
        # botão pai deixa de estar pressionado. O resultado histórico
        # fica no session_state para sobreviver a esse rerun.
        if st.button(
            "♻️ Procurar enriquecimento anterior no GitHub",
            type="secondary",
        ):
            with st.spinner(
                "Procurando versões anteriores do cache..."
            ):
                historical, history_error = (
                    github_find_historical_detail(
                        selected_fixture_id
                    )
                )

            if history_error:
                st.session_state["historical_detail"] = None
                st.session_state["historical_fixture_id"] = None
                st.error(history_error)
            elif historical:
                st.session_state["historical_detail"] = historical
                st.session_state["historical_fixture_id"] = selected_fixture_id
            else:
                st.session_state["historical_detail"] = None
                st.session_state["historical_fixture_id"] = selected_fixture_id
                st.info(
                    "Não encontrei um enriquecimento dessa partida "
                    "nas últimas versões do cache.json no GitHub."
                )

        historical = st.session_state.get("historical_detail")
        historical_fixture_id = st.session_state.get(
            "historical_fixture_id"
        )

        if (
            historical
            and historical_fixture_id == selected_fixture_id
        ):
            commit_date = historical.get("date") or "data desconhecida"

            st.success(
                "🟢 Enriquecimento encontrado no histórico "
                f"do GitHub ({commit_date})."
            )

            if st.button(
                "✅ Restaurar esse enriquecimento",
                type="primary",
            ):
                with st.spinner(
                    "Restaurando sem chamar a API-Sports..."
                ):
                    restored = restore_historical_detail(
                        cache,
                        selected_fixture_id,
                        historical,
                    )

                if restored is True:
                    st.session_state["historical_detail"] = None
                    st.session_state["historical_fixture_id"] = None

                    st.success(
                        "✅ Enriquecimento restaurado e confirmado "
                        "no cache do GitHub. Nenhuma chamada à "
                        "API-Sports foi feita."
                    )
                    st.rerun()

                elif isinstance(restored, tuple) and not restored[0]:
                    st.error(
                        f"Não foi possível restaurar: {restored[1]}"
                    )
                else:
                    st.error(
                        "Não foi possível restaurar o enriquecimento histórico."
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

                # ------------------------------------------------
                # CONFIRMAÇÃO PÓS-GRAVAÇÃO
                # ------------------------------------------------
                # Não fazemos rerun imediatamente: o rerun pode esconder
                # o resultado do teste e dificultar a identificação de uma
                # falha de persistência. Primeiro relemos o GitHub e
                # confirmamos que o detail realmente existe.
                verified_cache, _, verify_error = github_load_cache()

                if verify_error:
                    st.error(
                        "⚠️ A API-Sports respondeu, mas não foi possível "
                        f"confirmar a persistência no GitHub: {verify_error}"
                    )
                else:
                    verified_detail = (
                        (verified_cache or {})
                        .get("details", {})
                        .get(str(selected_fixture_id))
                    )

                    if verified_detail is None:
                        st.error(
                            "❌ A API-Sports foi consultada, mas o "
                            f"enriquecimento do fixture {selected_fixture_id} "
                            "não apareceu no cache do GitHub após a gravação. "
                            "Nenhum rerun será feito para não esconder o erro."
                        )
                    else:
                        # Mantém a tela atual coerente com o que realmente
                        # está persistido no GitHub.
                        cache = verified_cache
                        st.success(
                            "🟢 Enriquecimento concluído e confirmado no "
                            "GitHub. Nenhuma nova chamada será feita se "
                            "esta partida for aberta novamente."
                        )

                        st.info(
                            f"Fixture {selected_fixture_id}: registro em "
                            "`details` confirmado no cache persistente."
                        )

            else:

                st.info(
                    "O resultado já estava no cache. "
                    "Nenhuma chamada à API-Sports foi feita."
                )

# ============================================================
# DIAGNÓSTICO
# ============================================================

with st.expander(
    "🔎 Diagnóstico técnico"
):

    st.write(
        "IDs de campeonatos liberados no filtro:"
    )
    st.write(
        ", ".join(str(x) for x in sorted(ALLOWED_LEAGUE_IDS))
    )

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
        "O contador interno registra somente chamadas "
        "à API-Sports feitas pelo próprio app."
    )

    st.write(
        "O bloco de consumo real usa os headers de rate limit "
        "da API-Sports e o endpoint `/status` para mostrar "
        "o uso diário real da conta."
    )

    st.write(
        "A API-Sports informa separadamente o limite diário "
        "e o limite por minuto."
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
