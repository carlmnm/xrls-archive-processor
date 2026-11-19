#!/usr/bin/env python3
"""
XRLS Archive — Processador de filmes
====================================

Converte vídeos para MP4, embute legendas e adiciona capas (pôsteres do TMDB)
em UMA única passada do FFmpeg.

Uso:
    python processor6.py                       modo interativo
    python processor6.py filme.mkv outro.avi   processa direto (ou arraste os
                                               arquivos para cima do script)
    python processor6.py --setup               reconfigura chave do TMDB e preferências

Requisitos: Python 3.8+, FFmpeg e FFprobe no PATH.
Opcional:   pip install certifi  (certificados SSL atualizados)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections import deque
from dataclasses import asdict, dataclass, field, fields
from html import escape
from pathlib import Path
from typing import Optional

VERSAO = "6.0"
DATA_VERSAO = "Novembro 2026"

EXTENSOES_VIDEO = {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".m4v", ".webm", ".ts", ".flv", ".mpg", ".mpeg"}
EXTENSOES_LEGENDA = {".srt", ".ass", ".ssa", ".vtt"}
EXTENSOES_IMAGEM = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

# O que o contêiner MP4 aceita sem recodificar (conservador, pensando em TVs/Fire Stick)
CODECS_VIDEO_COPIAVEIS = {"h264", "hevc", "mpeg4"}
CODECS_AUDIO_COPIAVEIS = {"aac", "ac3", "eac3", "mp3"}
CODECS_LEGENDA_TEXTO = {"subrip", "srt", "ass", "ssa", "mov_text", "webvtt", "text"}

TMDB_API = "https://api.themoviedb.org/3"
TMDB_IMG = "https://image.tmdb.org/t/p"
USER_AGENT = f"xrls-archive/{VERSAO}"

IDIOMAS = {
    "por": "Português", "eng": "Inglês", "spa": "Espanhol", "fre": "Francês",
    "ger": "Alemão", "ita": "Italiano", "jpn": "Japonês", "kor": "Coreano",
    "rus": "Russo", "chi": "Chinês", "pob": "Português (Brasil)", "und": "Indefinido",
}
ALIAS_IDIOMA = {
    "pt": "por", "ptbr": "pob", "pt-br": "pob", "br": "pob", "portuguese": "por",
    "en": "eng", "english": "eng", "es": "spa", "spanish": "spa", "fr": "fre", "fra": "fre",
    "de": "ger", "deu": "ger", "it": "ita", "ja": "jpn", "ko": "kor", "ru": "rus",
    "zh": "chi", "zho": "chi",
}

ARQUIVO_ORIGINAIS = "originais"


class ErroProcessamento(Exception):
    """Falha esperada (arquivo inválido, ffmpeg falhou, rede...) com mensagem para o usuário."""


# =============================================================================
# Terminal: cores, mensagens e entrada
# =============================================================================

def _habilitar_ansi() -> bool:
    if not sys.stdout.isatty() or "NO_COLOR" in os.environ:
        return False
    if os.name == "nt":
        try:
            import ctypes
            kernel = ctypes.windll.kernel32
            handle = kernel.GetStdHandle(-11)
            modo = ctypes.c_uint32()
            if not kernel.GetConsoleMode(handle, ctypes.byref(modo)):
                return False
            return bool(kernel.SetConsoleMode(handle, modo.value | 0x0004))
        except Exception:
            os.system("")
    return True


for _fluxo in (sys.stdout, sys.stderr):
    try:
        _fluxo.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

COR = _habilitar_ansi()
RESET, NEGRITO, APAGADO = "\033[0m", "\033[1m", "\033[2m"
VERMELHO, VERDE, AMARELO, CIANO, CINZA = "\033[91m", "\033[92m", "\033[93m", "\033[96m", "\033[90m"


def pintar(texto: str, *estilos: str) -> str:
    return "".join(estilos) + texto + RESET if COR else texto


def largura_terminal() -> int:
    return shutil.get_terminal_size((90, 24)).columns


def ok(msg: str) -> None:
    print(f"{pintar('✓', VERDE, NEGRITO)} {msg}")


def aviso(msg: str) -> None:
    print(f"{pintar('!', AMARELO, NEGRITO)} {pintar(msg, AMARELO)}")


def erro(msg: str) -> None:
    print(f"{pintar('✗', VERMELHO, NEGRITO)} {pintar(msg, VERMELHO)}", file=sys.stderr)


def dica(msg: str) -> None:
    print(pintar(f"  {msg}", CINZA))


def secao(titulo: str) -> None:
    largura = min(largura_terminal(), 90)
    enfeite = "─" * max(3, largura - len(titulo) - 5)
    print(f"\n{pintar('──', CIANO)} {pintar(titulo, NEGRITO)} {pintar(enfeite, CIANO)}")


def perguntar(texto: str, padrao: str = "") -> str:
    sufixo = f" {pintar('[' + padrao + ']', CINZA)}" if padrao else ""
    resposta = input(f"{pintar('?', CIANO, NEGRITO)} {texto}{sufixo} › ").strip()
    return resposta or padrao


def confirmar(texto: str, padrao: bool = True) -> bool:
    marca = "S/n" if padrao else "s/N"
    while True:
        resposta = input(f"{pintar('?', CIANO, NEGRITO)} {texto} {pintar('[' + marca + ']', CINZA)} › ").strip().lower()
        if not resposta:
            return padrao
        if resposta in {"s", "sim", "y", "yes"}:
            return True
        if resposta in {"n", "nao", "não", "no"}:
            return False


def limpar_aspas(texto: str) -> str:
    """Remove aspas que o Windows coloca ao arrastar um arquivo para o terminal."""
    return texto.strip().strip('"').strip("'").strip()


# =============================================================================
# Formatação e utilitários
# =============================================================================

def fmt_tamanho(n: float) -> str:
    for unidade in ("B", "KB", "MB", "GB"):
        if n < 1024 or unidade == "GB":
            return f"{n:.0f} {unidade}" if unidade == "B" else f"{n:.1f} {unidade}"
        n /= 1024
    return f"{n:.1f} GB"


def fmt_tempo(segundos: float) -> str:
    segundos = max(0, int(segundos))
    h, resto = divmod(segundos, 3600)
    m, s = divmod(resto, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def abreviar(texto: str, limite: int) -> str:
    if len(texto) <= limite:
        return texto
    meio = (limite - 1) // 2
    return texto[:meio] + "…" + texto[-(limite - 1 - meio):]


def normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", sem_acento.lower()).strip()


def chave_caminho(p: Path) -> str:
    return os.path.normcase(str(p))


def mesmo_arquivo(a: Path, b: Path) -> bool:
    try:
        return a.samefile(b)
    except OSError:
        return False


def proximo_livre(caminho: Path) -> Path:
    """Devolve 'nome (1).ext', 'nome (2).ext'... se o caminho já existir."""
    if not caminho.exists():
        return caminho
    n = 1
    while True:
        candidato = caminho.with_name(f"{caminho.stem} ({n}){caminho.suffix}")
        if not candidato.exists():
            return candidato
        n += 1


def abrir_no_sistema(caminho: Path) -> None:
    try:
        if os.name == "nt":
            os.startfile(str(caminho))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(caminho)])
        else:
            subprocess.Popen(["xdg-open", str(caminho)])
    except Exception:
        pass


def parse_selecao(texto: str, validos: list) -> Optional[list]:
    """Converte '1,3,5-7' em [1,3,5,6,7] (só valores válidos). None se não for uma seleção numérica."""
    if not re.fullmatch(r"[\d,\s\-]+", texto):
        return None
    escolhidos: list = []
    for parte in texto.replace(" ", "").split(","):
        if not parte:
            continue
        try:
            if "-" in parte:
                ini, fim = (int(x) for x in parte.split("-", 1))
                itens = range(min(ini, fim), max(ini, fim) + 1)
            else:
                itens = [int(parte)]
        except ValueError:
            return None
        escolhidos += [i for i in itens if i in validos and i not in escolhidos]
    return escolhidos


# =============================================================================
# Configuração persistente
# =============================================================================

def pasta_config() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return base / "xrls"


ARQ_CONFIG = pasta_config() / "config.json"


@dataclass
class Config:
    tmdb_api_key: str = ""
    pasta_trabalho: str = str(Path.home() / "Downloads" / "para-realocar")
    originais: str = "mover"              # mover | manter | apagar
    animacao: bool = True
    abrir_galeria: bool = True
    idioma_legenda_padrao: str = "por"
    formato_nome: str = "{titulo}_{ano}"
    nome_minusculo: bool = True           # sugestões em minúsculas e separadas por "_"

    @classmethod
    def carregar(cls) -> "tuple[Config, bool]":
        try:
            dados = json.loads(ARQ_CONFIG.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls(), False
        validos = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in dados.items() if k in validos}), True

    def salvar(self) -> None:
        ARQ_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        ARQ_CONFIG.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.chmod(ARQ_CONFIG, 0o600)  # a chave da API é pessoal
        except OSError:
            pass

    @property
    def chave_tmdb(self) -> str:
        return (os.environ.get("TMDB_API_KEY") or self.tmdb_api_key).strip()


# =============================================================================
# FFmpeg / FFprobe
# =============================================================================

@dataclass
class Faixa:
    codec: str
    idioma: str = "und"
    titulo: str = ""
    canais: int = 0

    @property
    def e_texto(self) -> bool:
        return self.codec in CODECS_LEGENDA_TEXTO


@dataclass
class Midia:
    caminho: Path
    duracao: float
    tamanho: int
    codec_video: str
    largura: int
    altura: int
    audio: "list[Faixa]" = field(default_factory=list)
    legendas: "list[Faixa]" = field(default_factory=list)

    @property
    def video_copiavel(self) -> bool:
        return self.codec_video in CODECS_VIDEO_COPIAVEIS


def _executar(cmd: "list[str]") -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def sondar(caminho: Path) -> Midia:
    cp = _executar(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(caminho)])
    if cp.returncode != 0:
        raise ErroProcessamento(f"Não consegui ler o arquivo: {cp.stderr.strip() or 'ffprobe falhou'}")
    try:
        dados = json.loads(cp.stdout)
    except ValueError:
        raise ErroProcessamento("Resposta inválida do ffprobe.")

    video = None
    audio, legendas = [], []
    for s in dados.get("streams", []):
        tags = s.get("tags") or {}
        tipo = s.get("codec_type")
        if tipo == "video" and not (s.get("disposition") or {}).get("attached_pic"):
            video = video or s
        elif tipo == "audio":
            audio.append(Faixa(s.get("codec_name", "?"), tags.get("language", "und"), tags.get("title", ""),
                               int(s.get("channels") or 0)))
        elif tipo == "subtitle":
            legendas.append(Faixa(s.get("codec_name", "?"), tags.get("language", "und"), tags.get("title", "")))
    if video is None:
        raise ErroProcessamento("O arquivo não tem faixa de vídeo.")

    fmt = dados.get("format", {})
    try:
        duracao = float(fmt.get("duration") or video.get("duration") or 0)
    except ValueError:
        duracao = 0.0
    return Midia(caminho, duracao, int(fmt.get("size") or caminho.stat().st_size),
                 video.get("codec_name", "?"), int(video.get("width") or 0), int(video.get("height") or 0),
                 audio, legendas)


CHAVES_PROGRESSO = {"frame", "fps", "bitrate", "total_size", "out_time_us", "out_time_ms", "out_time",
                    "dup_frames", "drop_frames", "speed", "progress"}


def barra(fracao: float, largura: int = 24) -> str:
    cheio = int(round(max(0.0, min(1.0, fracao)) * largura))
    return pintar("█" * cheio, VERDE) + pintar("░" * (largura - cheio), CINZA)


def executar_ffmpeg(cmd: "list[str]", duracao: float, rotulo: str) -> None:
    """Roda o ffmpeg mostrando barra, velocidade e tempo restante. Levanta ErroProcessamento se falhar."""
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace", bufsize=1)
    except FileNotFoundError:
        raise ErroProcessamento("FFmpeg não encontrado. Instale e adicione ao PATH.")

    cauda: deque = deque(maxlen=12)
    inicio = time.monotonic()
    ultimo_desenho = 0.0
    velocidade = ""

    def desenhar(fracao: Optional[float], tempo_midia: float = 0.0) -> None:
        decorrido = time.monotonic() - inicio
        if fracao is None:
            linha = f"  {rotulo:<14} {pintar('decorrido ' + fmt_tempo(decorrido), CINZA)}"
        else:
            eta = decorrido * (1 - fracao) / fracao if fracao > 0.01 else 0
            extra = f"  {velocidade}" if velocidade else ""
            restante = f"  resta {fmt_tempo(eta)}" if 0.01 < fracao < 1 else ""
            linha = f"  {rotulo:<14} {barra(fracao)} {fracao * 100:5.1f}%{pintar(extra + restante, CINZA)}"
        sys.stdout.write("\r" + linha + "\033[K" if COR else "\r" + linha + "   ")
        sys.stdout.flush()

    try:
        for bruta in proc.stdout:  # type: ignore[union-attr]
            linha = bruta.strip()
            chave, sep, valor = linha.partition("=")
            if sep and (chave in CHAVES_PROGRESSO or chave.startswith("stream_")):
                if chave == "speed" and valor.strip() not in {"", "N/A"}:
                    velocidade = valor.strip()
                elif chave in {"out_time_us", "out_time_ms"}:
                    agora = time.monotonic()
                    if agora - ultimo_desenho < 0.1:
                        continue
                    try:
                        tempo = int(valor) / 1_000_000
                    except ValueError:
                        continue
                    if tempo >= 0:
                        ultimo_desenho = agora
                        desenhar(min(1.0, tempo / duracao) if duracao > 0 else None, tempo)
            elif linha:
                cauda.append(linha)
        codigo = proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        print()
        raise

    if codigo != 0:
        print()
        detalhe = "\n".join(f"    {l}" for l in cauda)
        raise ErroProcessamento(f"O FFmpeg falhou na etapa '{rotulo}'.\n{pintar(detalhe, CINZA)}")
    if duracao > 0:
        desenhar(1.0)
    print()


# =============================================================================
# Nomes de arquivo
# =============================================================================

RE_ANO = re.compile(r"^(?:19|20)\d{2}$")
RE_LIXO = re.compile(
    r"^(480p|576p|720p|1080p|2160p|4k|uhd|hdr\d*|bluray|blu-ray|bdrip|brrip|webrip|web-dl|webdl|hdrip|"
    r"dvdrip|hdtv|remux|x264|x265|h264|h265|hevc|avc|aac\d*|ac3|dts|dd5|atmos|10bit|dual|dublado|"
    r"legendado|nacional|extended|repack|proper|imax|yify|yts|rarbg)$", re.IGNORECASE)


def parse_titulo_ano(nome: str) -> "tuple[str, Optional[int]]":
    """'Matrix_1999', 'Matrix 1999' ou 'Matrix' → ('Matrix', 1999 | None)."""
    nome = nome.strip()
    m = re.match(r"(.+?)[_\s]+((?:19|20)\d{2})$", nome)
    if m:
        return m.group(1).replace("_", " ").strip(), int(m.group(2))
    return nome.replace("_", " ").strip(), None


def sugerir_titulo_ano(stem: str) -> "tuple[str, Optional[int]]":
    """Extrai título e ano de nomes de release ('The.Matrix.1999.1080p.BluRay.x264-GRUPO')."""
    stem = re.sub(r"(_(convertido|final|cover|utf8))+$", "", stem, flags=re.IGNORECASE)
    tokens = re.sub(r"[\[\](){}]", " ", re.sub(r"[._]+", " ", stem)).split()
    corte = next((i for i, t in enumerate(tokens) if RE_LIXO.match(t)), len(tokens))
    ano_idx = None
    for i in range(1, corte):
        if RE_ANO.match(tokens[i]):
            ano_idx = i
    if ano_idx is not None:
        return " ".join(tokens[:ano_idx]), int(tokens[ano_idx])
    titulo = " ".join(tokens[:corte]) or " ".join(tokens)
    return titulo, None


def sanitizar(nome: str) -> str:
    nome = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", nome)
    return re.sub(r"\s+", " ", nome).strip(" .")


def padronizar_nome(nome: str) -> str:
    """'The Matrix: Reloaded_2003' → 'the_matrix_reloaded_2003' (minúsculas, palavras separadas por '_')."""
    return re.sub(r"_+", "_", re.sub(r"[^\w]+", "_", nome.lower())).strip("_")


def formatar_nome(titulo: str, ano: Optional[int], formato: str, minusculo: bool = False) -> str:
    if not ano:
        nome = sanitizar(titulo)
    else:
        try:
            nome = sanitizar(formato.format(titulo=titulo, ano=ano))
        except (KeyError, IndexError, ValueError):
            nome = sanitizar(f"{titulo}_{ano}")
    return padronizar_nome(nome) if minusculo else nome


def detectar_idioma(nome_arquivo: str, padrao: str) -> str:
    stem = Path(nome_arquivo).stem.lower()
    m = re.search(r"[._\-\s\[(](pt[-_]?br|ptbr|pob|por|pt|portuguese|eng|en|english|spa|es|spanish|"
                  r"fre|fra|fr|ger|deu|de|ita|it|jpn|ja|kor|ko|rus|ru|chi|zho|zh)[\])]?$", stem)
    if not m:
        return padrao
    return normalizar_idioma(m.group(1).replace("_", "-"))


def normalizar_idioma(codigo: str) -> str:
    codigo = codigo.strip().lower()
    return ALIAS_IDIOMA.get(codigo, codigo if len(codigo) == 3 else (codigo or "und"))


# =============================================================================
# TMDB
# =============================================================================

def _contexto_ssl() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


class ErroRede(ErroProcessamento):
    pass


class TMDB:
    def __init__(self, chave: str) -> None:
        self.chave = chave.strip()
        self._ctx = _contexto_ssl()

    def _baixar(self, url: str, headers: Optional[dict] = None, tentativas: int = 3) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
        ultimo: Optional[Exception] = None
        for tentativa in range(tentativas):
            try:
                with urllib.request.urlopen(req, timeout=20, context=self._ctx) as resp:
                    return resp.read()
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    raise ErroRede("Chave da API do TMDB inválida (use --setup para corrigir).")
                if e.code in (403, 404):
                    raise ErroRede(f"TMDB respondeu {e.code}.")
                ultimo = e
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                ultimo = e
            time.sleep(1.0 * (tentativa + 1))
        raise ErroRede(f"Sem conexão com o TMDB ({ultimo}).")

    def _get(self, caminho: str, params: Optional[dict] = None) -> dict:
        params = dict(params or {})
        headers = {"Accept": "application/json"}
        if len(self.chave) > 40:  # token "Read Access" (v4)
            headers["Authorization"] = f"Bearer {self.chave}"
        else:
            params["api_key"] = self.chave
        return json.loads(self._baixar(f"{TMDB_API}{caminho}?{urllib.parse.urlencode(params)}", headers))

    def validar(self) -> bool:
        try:
            self._get("/configuration")
            return True
        except ErroProcessamento:
            return False

    def buscar_filmes(self, titulo: str, ano: Optional[int]) -> "list[dict]":
        base = {"query": titulo, "language": "pt-BR", "include_adult": "true"}
        resultados = self._get("/search/movie", {**base, **({"year": ano} if ano else {})}).get("results") or []
        if not resultados and ano:  # ano errado no nome do arquivo não deve impedir a busca
            resultados = self._get("/search/movie", base).get("results") or []
        return resultados[:5]

    def posters(self, filme_id: int) -> "list[dict]":
        dados = self._get(f"/movie/{filme_id}/images", {"language": "pt-BR", "include_image_language": "pt,en,null"})
        ordem = {"pt": 0, "en": 1, None: 2}
        posters = dados.get("posters") or []
        posters.sort(key=lambda p: (ordem.get(p.get("iso_639_1"), 3), -(p.get("vote_average") or 0)))
        return posters[:12]

    def baixar_poster(self, file_path: str, destino: Path) -> None:
        destino.write_bytes(self._baixar(f"{TMDB_IMG}/original{file_path}"))


def gerar_galeria(titulo: str, posters: "list[dict]", destino: Path) -> Path:
    """Página HTML local com todos os pôsteres numerados, para escolher olhando."""
    cartoes = []
    for i, p in enumerate(posters, 1):
        idioma = p.get("iso_639_1")
        rotulo = "Sem texto" if idioma is None else str(idioma).upper()
        cartoes.append(
            f'<figure><img loading="lazy" src="{TMDB_IMG}/w342{escape(p["file_path"])}" alt="Pôster {i}">'
            f'<span class="n">{i}</span><figcaption>{rotulo} · {p.get("width")}×{p.get("height")}</figcaption></figure>')
    destino.write_text(f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pôsteres — {escape(titulo)}</title>
<style>
  :root {{ color-scheme: dark; --bg:#0e1116; --card:#171b22; --txt:#e6e9ef; --mut:#8b93a1; --acc:#4fd1c5; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; padding:32px clamp(16px,4vw,48px); background:var(--bg); color:var(--txt);
         font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; }}
  h1 {{ margin:0 0 4px; font-size:22px; }}
  p {{ margin:0 0 24px; color:var(--mut); }}
  .grade {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(190px,1fr)); gap:20px; }}
  figure {{ position:relative; margin:0; background:var(--card); border-radius:12px; overflow:hidden;
           transition:transform .15s, box-shadow .15s; }}
  figure:hover {{ transform:translateY(-4px); box-shadow:0 12px 28px rgba(0,0,0,.5); }}
  img {{ display:block; width:100%; aspect-ratio:2/3; object-fit:cover; background:#222; }}
  .n {{ position:absolute; top:10px; left:10px; min-width:34px; padding:2px 10px; border-radius:999px;
       background:var(--acc); color:#06201d; font-weight:700; font-size:18px; text-align:center; }}
  figcaption {{ padding:10px 12px; color:var(--mut); font-size:13px; }}
</style></head><body>
<h1>{escape(titulo)}</h1>
<p>Volte ao terminal e digite o número do pôster escolhido.</p>
<div class="grade">{''.join(cartoes)}</div>
</body></html>""", encoding="utf-8")
    return destino


# =============================================================================
# Sessão (estado compartilhado durante a execução)
# =============================================================================

class Sessao:
    def __init__(self, cfg: Config, pasta: Path) -> None:
        self.cfg = cfg
        self.pasta = pasta
        self.tmdb: Optional[TMDB] = TMDB(cfg.chave_tmdb) if cfg.chave_tmdb else None
        self.reservados: set = set()
        self._tmp = tempfile.TemporaryDirectory(prefix="xrls_")
        self._contador = 0

    def arquivo_temp(self, sufixo: str) -> Path:
        self._contador += 1
        return Path(self._tmp.name) / f"{self._contador:03d}{sufixo}"

    def __enter__(self) -> "Sessao":
        return self

    def __exit__(self, *exc) -> None:
        self._tmp.cleanup()


# =============================================================================
# Planejamento interativo (todas as perguntas ANTES de processar)
# =============================================================================

@dataclass
class LegendaExterna:
    origem: Path
    arquivo: Path  # versão em UTF-8 usada no ffmpeg
    idioma: str


@dataclass
class Job:
    midia: Midia
    destino: Path
    titulo_meta: str
    extrair: "list[int]"
    manter: "list[int]"
    externas: "list[LegendaExterna]"
    capa: Optional[Path]


@dataclass
class Resultado:
    job: Job
    sucesso: bool
    mensagem: str = ""
    duracao: float = 0.0
    tamanho: int = 0


def listar_arquivos(pasta: Path, extensoes: set) -> "list[Path]":
    try:
        itens = [p for p in pasta.iterdir() if p.is_file() and p.suffix.lower() in extensoes and not p.name.startswith(".")]
    except OSError:
        return []
    return sorted(itens, key=lambda p: p.stat().st_mtime, reverse=True)


def mostrar_lista(arquivos: "list[Path]") -> None:
    larg = max(20, largura_terminal() - 22)
    print(pintar(f"  {'#':>3}  {'Arquivo':<{larg}}  Tamanho", CINZA))
    for i, p in enumerate(arquivos, 1):
        print(f"  {pintar(f'{i:>3}', CIANO, NEGRITO)}  {abreviar(p.name, larg):<{larg}}  {fmt_tamanho(p.stat().st_size):>9}")


def escolher_arquivos(pasta: Path) -> "Optional[list[Path]]":
    """Mostra os vídeos da pasta. Aceita número, faixa (1-3), 'todos', parte do nome ou arrastar arquivo."""
    videos = listar_arquivos(pasta, EXTENSOES_VIDEO)
    lista = videos
    while True:
        secao("Vídeos")
        if lista:
            mostrar_lista(lista)
            dica("Número · vários (1,3 ou 2-4) · 'todos' · parte do nome · arraste um arquivo · 'sair'")
            padrao = "1"
        else:
            aviso(f"Nenhum vídeo em {pasta}")
            dica("Coloque arquivos lá e pressione Enter para atualizar, arraste um arquivo, ou digite 'sair'.")
            padrao = ""
        resposta = limpar_aspas(perguntar("O que processar?", padrao))
        baixo = resposta.lower()

        if baixo in {"sair", "q", "quit", "exit"}:
            return None
        if not resposta:
            videos = lista = listar_arquivos(pasta, EXTENSOES_VIDEO)
            continue
        if baixo in {"todos", "all", "*"}:
            return list(lista)

        caminho = Path(resposta).expanduser()
        for candidato in (caminho, pasta / resposta):
            if candidato.is_file():
                return [candidato]

        numeros = parse_selecao(resposta, list(range(1, len(lista) + 1)))
        if numeros is not None:
            if numeros:
                return [lista[n - 1] for n in numeros]
            aviso("Número fora da lista.")
            continue

        termos = normalizar(resposta).split()
        achados = [p for p in videos if all(t in normalizar(p.name) for t in termos)]
        if len(achados) == 1:
            return achados
        if achados:
            lista = achados
            continue
        aviso("Nada encontrado com esse nome.")
        lista = videos


def destino_unico(pasta: Path, nome: str, fonte: Path, reservados: set) -> Path:
    def ocupado(c: Path) -> bool:
        if chave_caminho(c) in reservados:
            return True
        return c.exists() and not mesmo_arquivo(c, fonte)

    candidato, n = pasta / f"{nome}.mp4", 1
    while ocupado(candidato):
        candidato = pasta / f"{nome} ({n}).mp4"
        n += 1
    reservados.add(chave_caminho(candidato))
    return candidato


def garantir_utf8(origem: Path, sessao: Sessao) -> Path:
    """Devolve um arquivo de legenda em UTF-8 (converte de cp1252/latin-1/utf-16 se necessário)."""
    bruto = origem.read_bytes()
    try:
        bruto.decode("utf-8-sig")
        return origem
    except UnicodeDecodeError:
        pass
    if bruto.startswith((b"\xff\xfe", b"\xfe\xff")):
        texto, enc = bruto.decode("utf-16"), "utf-16"
    else:
        try:
            texto, enc = bruto.decode("cp1252"), "cp1252"
        except UnicodeDecodeError:
            texto, enc = bruto.decode("latin-1"), "latin-1"
    destino = sessao.arquivo_temp(origem.suffix)
    with open(destino, "w", encoding="utf-8", newline="") as f:
        f.write(texto)
    dica(f"'{origem.name}' convertida de {enc} para UTF-8")
    return destino


def preparar_imagem(caminho: Path, sessao: Sessao) -> Path:
    """MP4 só aceita JPEG/PNG como capa: converte qualquer outro formato."""
    if caminho.suffix.lower() in {".jpg", ".jpeg", ".png"}:
        return caminho
    saida = sessao.arquivo_temp(".jpg")
    cp = _executar(["ffmpeg", "-y", "-loglevel", "error", "-i", str(caminho), "-frames:v", "1", "-q:v", "2", str(saida)])
    if cp.returncode != 0 or not saida.exists():
        raise ErroProcessamento(f"Não consegui converter a imagem '{caminho.name}'.")
    return saida


def _capa_local(sessao: Sessao) -> Optional[Path]:
    imagens = listar_arquivos(sessao.pasta, EXTENSOES_IMAGEM)[:8]
    if imagens:
        print("  Imagens na pasta:")
        for i, p in enumerate(imagens, 1):
            print(f"  {pintar(f'{i:>3}', CIANO, NEGRITO)}  {p.name}")
    resposta = limpar_aspas(perguntar("Imagem (número, caminho ou arraste o arquivo; Enter volta)"))
    if not resposta:
        return None
    if resposta.isdigit() and 1 <= int(resposta) <= len(imagens):
        return preparar_imagem(imagens[int(resposta) - 1], sessao)
    caminho = Path(resposta).expanduser()
    if not caminho.is_absolute():
        caminho = sessao.pasta / caminho
    if not caminho.is_file():
        aviso(f"Arquivo não encontrado: {caminho}")
        return None
    return preparar_imagem(caminho, sessao)


def _menu_filme(filmes: "list[dict]") -> "tuple[str, object]":
    if filmes:
        for i, f in enumerate(filmes, 1):
            ano = (f.get("release_date") or "")[:4] or "s/ano"
            original = f.get("original_title")
            extra = f" · {original}" if original and original != f.get("title") else ""
            nota = f" · ★ {f['vote_average']:.1f}" if f.get("vote_average") else ""
            print(f"  {pintar(f'{i:>3}', CIANO, NEGRITO)}  {f.get('title')} ({ano}){pintar(extra + nota, CINZA)}")
        dica("Enter = 1 · número · n = nova busca · l = imagem local · p = pular capa")
        padrao = "1"
    else:
        aviso("Nenhum filme encontrado.")
        dica("n = nova busca · l = imagem local · p = pular capa")
        padrao = "n"
    while True:
        r = perguntar("Qual filme?", padrao).strip()
        baixo = r.lower()
        if baixo == "p":
            return "pular", None
        if baixo == "l":
            return "local", None
        if baixo == "n":
            nova = perguntar("Nova busca (ex: Matrix 1999)")
            if nova:
                return "nova", nova
            continue
        if r.isdigit() and 1 <= int(r) <= len(filmes):
            return "filme", filmes[int(r) - 1]
        if len(r) > 1 and not r.isdigit():
            return "nova", r


def _menu_posters(sessao: Sessao, filme: dict, cfg: Config) -> "object":
    tmdb = sessao.tmdb
    assert tmdb is not None
    try:
        posters = tmdb.posters(filme["id"])
    except ErroProcessamento as e:
        aviso(str(e))
        return "voltar"
    if not posters:
        aviso("Esse filme não tem pôsteres no TMDB.")
        return "voltar"

    nome_filme = f"{filme.get('title')} ({(filme.get('release_date') or '')[:4]})"
    for i, p in enumerate(posters, 1):
        idioma = p.get("iso_639_1")
        print(f"  {pintar(f'{i:>3}', CIANO, NEGRITO)}  {'sem texto' if idioma is None else idioma:<10}"
              f"{pintar(str(p.get('width')) + '×' + str(p.get('height')), CINZA)}")
    if cfg.abrir_galeria:
        galeria = gerar_galeria(nome_filme, posters, sessao.arquivo_temp(".html"))
        try:
            webbrowser.open(galeria.as_uri())
            dica("Abri uma galeria no navegador para você escolher olhando.")
        except Exception:
            pass
    dica("Enter = 1 · número · v = voltar · l = imagem local · p = pular capa")
    while True:
        r = perguntar("Qual pôster?", "1").strip().lower()
        if r in {"p", "l", "v"}:
            return {"p": "pular", "l": "local", "v": "voltar"}[r]
        if r.isdigit() and 1 <= int(r) <= len(posters):
            destino = sessao.arquivo_temp(".jpg")
            try:
                print(pintar("  Baixando pôster…", CINZA))
                tmdb.baixar_poster(posters[int(r) - 1]["file_path"], destino)
                return destino
            except ErroProcessamento as e:
                aviso(str(e))


def escolher_capa(nome: str, sessao: Sessao) -> Optional[Path]:
    """Fluxo único de capa: busca no TMDB → escolhe filme → escolhe pôster (ou usa imagem local)."""
    if sessao.tmdb is None:
        aviso("Chave do TMDB não configurada (rode com --setup). Só imagem local disponível.")
        return _capa_local(sessao)
    consulta = nome
    while True:
        titulo, ano = parse_titulo_ano(consulta)
        print(pintar(f"\n  Buscando '{titulo}'{f' ({ano})' if ano else ''} no TMDB…", CINZA))
        try:
            filmes = sessao.tmdb.buscar_filmes(titulo, ano)
        except ErroProcessamento as e:
            aviso(str(e))
            filmes = []
        acao, valor = _menu_filme(filmes)
        if acao == "pular":
            return None
        if acao == "nova":
            consulta = str(valor)
            continue
        if acao == "local":
            imagem = _capa_local(sessao)
            if imagem:
                return imagem
            continue
        resultado = _menu_posters(sessao, valor, sessao.cfg)  # type: ignore[arg-type]
        if isinstance(resultado, Path):
            return resultado
        if resultado == "pular":
            return None
        if resultado == "local":
            imagem = _capa_local(sessao)
            if imagem:
                return imagem


def descrever_faixas(midia: Midia) -> None:
    for i, s in enumerate(midia.legendas):
        info = f"{s.idioma} · {s.codec}" + (f" · {s.titulo}" if s.titulo else "")
        extra = "" if s.e_texto else pintar("  (imagem: não dá para extrair/manter)", AMARELO)
        print(f"  {pintar(f'[{i}]', CIANO, NEGRITO)} {info}{extra}")


def pedir_faixas(texto: str, validos: "list[int]", padrao_todas: bool) -> "list[int]":
    r = perguntar(texto, "todas" if padrao_todas else "nenhuma").lower()
    if r in {"todas", "t", "all", "*"}:
        return list(validos)
    if r in {"nenhuma", "nenhum", "n", "-"}:
        return []
    escolhidas = parse_selecao(r, validos)
    if not escolhidas:
        aviso("Seleção inválida; ignorando.")
        return []
    return escolhidas


def planejar_legendas_embutidas(midia: Midia) -> "tuple[list[int], list[int]]":
    if not midia.legendas:
        return [], []
    secao("Legendas embutidas")
    descrever_faixas(midia)
    texto = [i for i, s in enumerate(midia.legendas) if s.e_texto]
    if not texto:
        return [], []
    extrair = pedir_faixas("Extrair para .srt?", texto, False)
    manter = pedir_faixas("Manter dentro do MP4?", texto, midia.caminho.suffix.lower() == ".mp4")
    repetidas = sorted(set(extrair) & set(manter))
    if repetidas:
        aviso(f"Legenda(s) {', '.join(map(str, repetidas))} em 'extrair' e 'manter': alguns players vão mostrá-la "
              "duas vezes (o .srt solto é carregado junto com o vídeo).")
    return extrair, manter


def planejar_legendas_externas(fonte: Path, sessao: Sessao) -> "list[LegendaExterna]":
    candidatas = listar_arquivos(sessao.pasta, EXTENSOES_LEGENDA)
    base = normalizar(fonte.stem)
    candidatas.sort(key=lambda p: not normalizar(p.stem).startswith(base))
    sugeridas = [i for i, p in enumerate(candidatas, 1) if normalizar(p.stem).startswith(base)]

    secao("Legendas externas")
    escolhidas: "list[Path]" = []
    if candidatas:
        for i, p in enumerate(candidatas, 1):
            marca = pintar("  ★ combina com o vídeo", VERDE) if i in sugeridas else ""
            print(f"  {pintar(f'{i:>3}', CIANO, NEGRITO)}  {p.name}{marca}")
        dica("Número(s) · arraste um arquivo · 'nenhuma'")
        padrao = ",".join(map(str, sugeridas)) if sugeridas else "nenhuma"
        r = limpar_aspas(perguntar("Quais embutir?", padrao))
        if r.lower() not in {"nenhuma", "n", ""}:
            caminho = Path(r).expanduser()
            if caminho.is_file():
                escolhidas = [caminho]
            else:
                nums = parse_selecao(r, list(range(1, len(candidatas) + 1))) or []
                escolhidas = [candidatas[n - 1] for n in nums]
    else:
        r = limpar_aspas(perguntar("Arraste uma legenda aqui (Enter para pular)"))
        if r:
            caminho = Path(r).expanduser()
            if not caminho.is_absolute():
                caminho = sessao.pasta / caminho
            if caminho.is_file():
                escolhidas = [caminho]
            else:
                aviso("Arquivo não encontrado.")

    externas = []
    for p in escolhidas:
        sugerido = detectar_idioma(p.name, sessao.cfg.idioma_legenda_padrao)
        idioma = normalizar_idioma(perguntar(f"Idioma de '{abreviar(p.name, 40)}'", sugerido))
        externas.append(LegendaExterna(p, garantir_utf8(p, sessao), idioma))
    return externas


def planejar(fonte: Path, apenas_capa: bool, sessao: Sessao, posicao: int, total: int) -> Optional[Job]:
    try:
        midia = sondar(fonte)
    except ErroProcessamento as e:
        erro(f"{fonte.name}: {e}")
        return None

    secao(f"Arquivo {posicao}/{total}")
    print(f"  {pintar(fonte.name, NEGRITO)}")
    audio = ", ".join(f"{a.codec}{f' {a.canais}ch' if a.canais else ''}" for a in midia.audio) or "nenhum"
    dica(f"{fmt_tempo(midia.duracao)} · {midia.largura}×{midia.altura} · vídeo {midia.codec_video} · "
         f"áudio {audio} · {len(midia.legendas)} legenda(s) · {fmt_tamanho(midia.tamanho)}")

    titulo_sug, ano_sug = sugerir_titulo_ano(fonte.stem)
    sugestao = formatar_nome(titulo_sug, ano_sug, sessao.cfg.formato_nome, sessao.cfg.nome_minusculo)
    dica("Use Título_Ano (ajuda a achar o pôster). '=' mantém o nome atual.")
    resposta = perguntar("Nome final do filme", sugestao)
    nome = fonte.stem if resposta == "=" else resposta
    if Path(nome).suffix.lower() in EXTENSOES_VIDEO:
        nome = Path(nome).stem
    nome = sanitizar(nome) or fonte.stem

    destino = destino_unico(sessao.pasta, nome, fonte, sessao.reservados)
    if destino.stem != nome:
        aviso(f"Já existe '{nome}.mp4'; vou salvar como '{destino.name}'.")

    capa = None
    secao("Capa")
    try:
        capa = escolher_capa(nome, sessao)
    except ErroProcessamento as e:
        aviso(str(e))

    extrair: "list[int]" = []
    manter: "list[int]" = []
    externas: "list[LegendaExterna]" = []
    if apenas_capa:
        manter = [i for i, s in enumerate(midia.legendas) if s.e_texto]
    else:
        extrair, manter = planejar_legendas_embutidas(midia)
        externas = planejar_legendas_externas(fonte, sessao)

    return Job(midia, destino, parse_titulo_ano(nome)[0], extrair, manter, externas, capa)


def resumir(jobs: "list[Job]", sessao: Sessao) -> "list[str]":
    """Imprime o plano completo e devolve os avisos relevantes."""
    avisos = []
    secao("Resumo")
    politica = sessao.cfg.originais
    for n, job in enumerate(jobs, 1):
        m = job.midia
        print(f"\n  {pintar(str(n) + '.', CIANO, NEGRITO)} {m.caminho.name}  {pintar('→', CINZA)}  {pintar(job.destino.name, VERDE, NEGRITO)}")
        if m.video_copiavel:
            video = f"copiar ({m.codec_video})"
        else:
            video = f"recodificar {m.codec_video} → h264"
            avisos.append(f"'{m.caminho.name}': vídeo {m.codec_video} será recodificado (demora bem mais).")
        audios = ", ".join("copiar" if a.codec in CODECS_AUDIO_COPIAVEIS else f"{a.codec}→aac" for a in m.audio) or "nenhum"
        print(f"     {pintar('vídeo', CINZA)}   {video}")
        print(f"     {pintar('áudio', CINZA)}   {audios}")
        legs = [f"{m.legendas[i].idioma} (embutida)" for i in job.manter] + [f"{l.idioma} ({l.origem.name})" for l in job.externas]
        print(f"     {pintar('legendas', CINZA)} {', '.join(legs) if legs else 'nenhuma'}")
        if job.extrair:
            print(f"     {pintar('extrair', CINZA)}  {len(job.extrair)} arquivo(s) .srt")
        print(f"     {pintar('capa', CINZA)}     {'sim' if job.capa else 'não'}")
        if job.destino == m.caminho:
            print(f"     {pintar('original', CINZA)} atualizado no lugar")
        elif politica != "manter" and m.caminho.parent == sessao.pasta:
            destino_orig = f"pasta '{ARQUIVO_ORIGINAIS}'" if politica == "mover" else "APAGADO"
            print(f"     {pintar('original', CINZA)} {destino_orig}")
    try:
        livre = shutil.disk_usage(sessao.pasta).free
        precisa = sum(j.midia.tamanho for j in jobs)
        if livre < precisa * 1.1:
            avisos.append(f"Pouco espaço em disco: livre {fmt_tamanho(livre)}, estimado {fmt_tamanho(precisa)}.")
    except OSError:
        pass
    return avisos


# =============================================================================
# Execução
# =============================================================================

def montar_comando(job: Job, saida: Path) -> "list[str]":
    """Monta UM comando ffmpeg que converte, embute legendas e anexa a capa de uma vez."""
    m = job.midia
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostats", "-progress", "pipe:1", "-y", "-i", str(m.caminho)]
    entrada, entradas_ext = 1, []
    for leg in job.externas:
        cmd += ["-i", str(leg.arquivo)]
        entradas_ext.append(entrada)
        entrada += 1
    entrada_capa = None
    if job.capa:
        cmd += ["-i", str(job.capa)]
        entrada_capa = entrada

    cmd += ["-map", "0:V:0"]
    for i in range(len(m.audio)):
        cmd += ["-map", f"0:a:{i}"]
    for i in job.manter:
        cmd += ["-map", f"0:s:{i}"]
    for e in entradas_ext:
        cmd += ["-map", f"{e}:s:0"]
    if entrada_capa is not None:
        cmd += ["-map", f"{entrada_capa}:v:0"]

    if m.video_copiavel:
        cmd += ["-c:v:0", "copy"]
        if m.codec_video == "hevc":
            cmd += ["-tag:v:0", "hvc1"]  # compatibilidade com Apple/TVs
    else:
        cmd += ["-c:v:0", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p"]
    if entrada_capa is not None:
        cmd += ["-c:v:1", "copy", "-disposition:v:1", "attached_pic"]

    for i, a in enumerate(m.audio):
        if a.codec in CODECS_AUDIO_COPIAVEIS:
            cmd += [f"-c:a:{i}", "copy"]
        else:
            cmd += [f"-c:a:{i}", "aac", f"-b:a:{i}", "384k" if a.canais > 2 else "192k"]
            if a.canais >= 6:
                cmd += [f"-ac:a:{i}", "6"]

    faixas = [(m.legendas[i].idioma, m.legendas[i].titulo) for i in job.manter] + [(l.idioma, "") for l in job.externas]
    if faixas:
        cmd += ["-c:s", "mov_text"]
        padrao = next((n for n, (idioma, _) in enumerate(faixas) if idioma in {"por", "pob"}), 0)
        for n, (idioma, titulo) in enumerate(faixas):
            nome = titulo or IDIOMAS.get(idioma, idioma.upper())
            # O MP4 descarta a tag "title"; o nome visível da faixa vai em "handler_name".
            cmd += [f"-metadata:s:s:{n}", f"language={idioma}", f"-metadata:s:s:{n}", f"handler_name={nome}",
                    f"-disposition:s:{n}", "default" if n == padrao else "0"]

    cmd += ["-map_metadata", "0", "-map_chapters", "0", "-metadata", f"title={job.titulo_meta}",
            "-movflags", "+faststart", "-f", "mp4", str(saida)]
    return cmd


def extrair_legendas(job: Job) -> None:
    for idx in job.extrair:
        faixa = job.midia.legendas[idx]
        saida = proximo_livre(job.destino.with_name(f"{job.destino.stem}.{faixa.idioma}.srt"))
        cp = _executar(["ffmpeg", "-y", "-loglevel", "error", "-i", str(job.midia.caminho),
                        "-map", f"0:s:{idx}", "-c:s", "srt", str(saida)])
        if cp.returncode == 0 and saida.exists():
            ok(f"Legenda [{idx}] extraída → {saida.name}")
        else:
            aviso(f"Não consegui extrair a legenda [{idx}].")


def tratar_original(job: Job, sessao: Sessao) -> None:
    fonte = job.midia.caminho
    if mesmo_arquivo(fonte, job.destino) or not fonte.exists():
        return
    if fonte.parent != sessao.pasta or sessao.cfg.originais == "manter":
        return  # nunca mexe em arquivos de fora da pasta de trabalho
    if sessao.cfg.originais == "apagar":
        fonte.unlink()
    else:
        pasta_orig = sessao.pasta / ARQUIVO_ORIGINAIS
        pasta_orig.mkdir(exist_ok=True)
        shutil.move(str(fonte), str(proximo_livre(pasta_orig / fonte.name)))


def executar_job(job: Job, sessao: Sessao) -> Resultado:
    inicio = time.monotonic()
    parcial = job.destino.with_name(job.destino.name + ".parte")
    try:
        extrair_legendas(job)
        executar_ffmpeg(montar_comando(job, parcial), job.midia.duracao, "Processando")
        if not parcial.exists() or parcial.stat().st_size == 0:
            raise ErroProcessamento("O FFmpeg não gerou o arquivo de saída.")
        os.replace(parcial, job.destino)
        tratar_original(job, sessao)
        return Resultado(job, True, duracao=time.monotonic() - inicio, tamanho=job.destino.stat().st_size)
    except ErroProcessamento as e:
        return Resultado(job, False, str(e), time.monotonic() - inicio)
    finally:
        if parcial.exists():
            try:
                parcial.unlink()
            except OSError:
                pass


def processar_fila(jobs: "list[Job]", sessao: Sessao) -> "list[Resultado]":
    resultados: "list[Resultado]" = []
    for n, job in enumerate(jobs, 1):
        secao(f"Processando {n}/{len(jobs)} — {abreviar(job.destino.name, 50)}")
        try:
            r = executar_job(job, sessao)
        except KeyboardInterrupt:
            aviso("Cancelado pelo usuário.")
            resultados.append(Resultado(job, False, "cancelado"))
            if n < len(jobs) and confirmar("Continuar com os próximos?", True):
                continue
            break
        resultados.append(r)
        if r.sucesso:
            ok(f"Concluído em {fmt_tempo(r.duracao)} · {fmt_tamanho(r.tamanho)}")
        else:
            erro(r.mensagem)
    return resultados


def mostrar_relatorio(resultados: "list[Resultado]") -> None:
    secao("Relatório")
    for r in resultados:
        if r.sucesso:
            print(f"  {pintar('✓', VERDE, NEGRITO)} {r.job.destino.name}  {pintar(f'{fmt_tamanho(r.tamanho)} · {fmt_tempo(r.duracao)}', CINZA)}")
        else:
            print(f"  {pintar('✗', VERMELHO, NEGRITO)} {r.job.midia.caminho.name}  {pintar('falhou', CINZA)}")
    feitos = sum(r.sucesso for r in resultados)
    print(f"\n  {pintar(f'{feitos}/{len(resultados)} concluído(s)', NEGRITO)}")
    sys.stdout.write("\a")
    sys.stdout.flush()


# =============================================================================
# Configuração guiada, banner e programa principal
# =============================================================================

def configurar(cfg: Config, primeira_vez: bool) -> None:
    secao("Configuração" + (" inicial" if primeira_vez else ""))
    if primeira_vez:
        print("  Vamos deixar tudo pronto — isso é feito uma vez só.\n")

    atual = f"termina em …{cfg.tmdb_api_key[-4:]}" if cfg.tmdb_api_key else "nenhuma"
    dica("Chave gratuita em https://www.themoviedb.org/settings/api (aceita a chave v3 ou o token de leitura).")
    nova = perguntar(f"Chave da API do TMDB (atual: {atual}; Enter mantém)").strip()
    if nova:
        cfg.tmdb_api_key = nova
        print(pintar("  Testando chave…", CINZA))
        ok("Chave válida!") if TMDB(nova).validar() else aviso("Não consegui validar agora (sem internet?). Salvei mesmo assim.")

    cfg.pasta_trabalho = perguntar("Pasta de trabalho", cfg.pasta_trabalho)
    print("  Depois de processar, o que fazer com o arquivo original?")
    print("   1 - Mover para a subpasta 'originais' (seguro)\n   2 - Manter onde está\n   3 - Apagar")
    escolha = perguntar("Opção", {"mover": "1", "manter": "2", "apagar": "3"}.get(cfg.originais, "1"))
    cfg.originais = {"1": "mover", "2": "manter", "3": "apagar"}.get(escolha, cfg.originais)
    cfg.nome_minusculo = confirmar("Sugerir nomes em minúsculas separados por _ (ex: the_matrix_1999)?", cfg.nome_minusculo)
    cfg.animacao = confirmar("Mostrar a animação de abertura?", cfg.animacao)
    cfg.salvar()
    ok(f"Configurações salvas em {ARQ_CONFIG}")


ARTE_TITULO = [
    '       _  __ ____   __    _____',
    '      | |/ // __ \\ / /   / ___/',
    '      |   // /_/ // /    \\__ \\',
    '     /   |/ _, _// /___ ___/ /',
    '    /_/|_/_/ |_|/_____//____/',
    '        ___    ____  ______ __  __ ____ _    __ ______',
    '       /   |  / __ \\/ ____// / / //  _/| |  / // ____/',
    '      / /| | / /_/ / /    / /_/ / / /  | | / // __/',
    '     / ___ |/ _, _/ /___ / __  /_/ /   | |/ // /___',
    '    /_/  |_/_/ |_|\\____//_/ /_//___/   |___//_____/',
]

BANNER_LARGURA = 76


def montar_banner() -> "list[str]":
    def linha(txt: str = "") -> str:
        return " █" + txt.ljust(BANNER_LARGURA) + "█"

    barra_h = "─" * BANNER_LARGURA
    corpo = [linha(), *(linha(l) for l in ARTE_TITULO), linha(), linha(barra_h),
             linha(". : P R O U D L Y   P R E S E N T S : .".center(BANNER_LARGURA)), linha(barra_h), linha(),
             linha("   > CRIADOR.: xrlsmkl"), linha("   > Capas, legendas e conversão"),
             linha(f"   > VERSAO..: {VERSAO} · {DATA_VERSAO}"), linha()]
    return [" " + "▄" * (BANNER_LARGURA + 2), *corpo, " " + "▀" * (BANNER_LARGURA + 2)]


def exibir_banner(animar: bool, duracao: float = 1.6, fps: int = 25) -> None:
    linhas = montar_banner()
    if largura_terminal() < BANNER_LARGURA + 4:
        print(pintar(f"\n XRLS ARCHIVE · {VERSAO}", NEGRITO, CIANO))
        return
    if not COR:
        print("\n".join(linhas))
        return

    fr, fg, fb = (random.uniform(0.05, 0.15) for _ in range(3))
    pr, pg, pb = (random.uniform(0, 6.28) for _ in range(3))

    def quadro(deslocamento: float) -> str:
        cores = []
        for col in range(len(linhas[0])):
            x = col - deslocamento
            r, g, b = (int(math.sin(f * x + p) * 127 + 128) for f, p in ((fr, pr), (fg, pg), (fb, pb)))
            cores.append(f"\033[38;2;{r};{g};{b}m")
        return "\n".join("".join(c + ch if ch != " " else " " for c, ch in zip(cores, l)) + RESET for l in linhas)

    if not animar:
        print(quadro(0))
        return
    sys.stdout.write("\033[?25l" + "\n" * len(linhas))
    try:
        for frame in range(int(duracao * fps)):
            sys.stdout.write(f"\033[{len(linhas)}A\r{quadro(frame * 2.0)}\n")
            sys.stdout.flush()
            time.sleep(1.0 / fps)
    finally:
        sys.stdout.write("\033[?25h")


def verificar_dependencias() -> None:
    faltando = [n for n in ("ffmpeg", "ffprobe") if shutil.which(n) is None]
    if faltando:
        erro(f"Não encontrei: {', '.join(faltando)}.")
        dica("Windows:  winget install Gyan.FFmpeg   (depois feche e reabra o terminal)")
        dica("macOS:    brew install ffmpeg")
        dica("Linux:    sudo apt install ffmpeg")
        sys.exit(1)


def perguntar_modo() -> bool:
    """True = só capa/nome; False = fluxo completo."""
    secao("O que fazer?")
    print("   1 - Completo: converter para MP4 + legendas + capa")
    print("   2 - Só capa e nome (não mexe nas legendas)")
    return perguntar("Opção", "1") == "2"


def ciclo(arquivos: "list[Path]", sessao: Sessao) -> None:
    apenas_capa = perguntar_modo()
    jobs = []
    for n, fonte in enumerate(arquivos, 1):
        job = planejar(fonte, apenas_capa, sessao, n, len(arquivos))
        if job:
            jobs.append(job)
    if not jobs:
        return
    for a in resumir(jobs, sessao):
        aviso(a)
    print()
    if not confirmar(f"Iniciar {len(jobs)} arquivo(s)? Depois é só esperar", True):
        aviso("Nada foi alterado.")
        return
    resultados = processar_fila(jobs, sessao)
    mostrar_relatorio(resultados)
    if any(r.sucesso for r in resultados) and confirmar("Abrir a pasta?", False):
        abrir_no_sistema(sessao.pasta)


def main(argv: "Optional[list[str]]" = None) -> int:
    ap = argparse.ArgumentParser(description="XRLS Archive — converte vídeos para MP4, com legendas e capa.")
    ap.add_argument("arquivos", nargs="*", help="vídeos a processar (ou arraste sobre o script)")
    ap.add_argument("--dir", help="pasta de trabalho (sobrepõe a configuração)")
    ap.add_argument("--setup", action="store_true", help="reconfigura chave do TMDB e preferências")
    ap.add_argument("--sem-animacao", action="store_true", help="pula a animação de abertura")
    ap.add_argument("--version", action="version", version=f"xrls-archive {VERSAO}")
    args = ap.parse_args(argv)

    cfg, existia = Config.carregar()
    try:
        exibir_banner(cfg.animacao and not args.sem_animacao)
        verificar_dependencias()
        if args.setup or not existia:
            configurar(cfg, primeira_vez=not existia)
        pasta = Path(args.dir or cfg.pasta_trabalho).expanduser().resolve()
        pasta.mkdir(parents=True, exist_ok=True)

        with Sessao(cfg, pasta) as sessao:
            pendentes = [Path(limpar_aspas(a)).expanduser().resolve() for a in args.arquivos]
            for p in [p for p in pendentes if not p.is_file()]:
                aviso(f"Ignorando (não existe): {p}")
            pendentes = [p for p in pendentes if p.is_file()]
            da_linha_de_comando = bool(pendentes)
            while True:
                arquivos = pendentes or escolher_arquivos(pasta)
                pendentes = []
                if not arquivos:
                    break
                ciclo(arquivos, sessao)
                if da_linha_de_comando and not confirmar("Processar mais algum arquivo?", False):
                    break
                da_linha_de_comando = False
    except (KeyboardInterrupt, EOFError):
        print()
    print(pintar("\nAté logo! 🎬", CIANO))
    return 0


if __name__ == "__main__":
    sys.exit(main())
