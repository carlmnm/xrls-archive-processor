#!/usr/bin/env python3

import os
import sys
import re
import json
import shutil
import subprocess
import time
import urllib.request
import urllib.parse
import ssl
import certifi
import random
import math
from typing import List, Tuple, Optional

# --- ATIVAÇÃO DE CORES (ANSI) NO WINDOWS 10 ---
if os.name == 'nt':
    os.system("") # Hack simples para ativar o ENABLE_VIRTUAL_TERMINAL_PROCESSING no CMD

# --- CONFIGURAÇÃO DE CORES NATIVAS (SUBSTITUINDO COLORAMA) ---
class Color:
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    RESET = "\033[0m"

class Fore:
    GREEN = Color.GREEN
    YELLOW = Color.YELLOW
    RED = Color.RED
    CYAN = Color.CYAN
    RESET = Color.RESET

# --- CONFIGURAÇÃO DE DIRETÓRIO ---
# No Windows, o ~ é expandido para a pasta do usuário (ex: C:\Users\Nome)
WORK_DIR = os.path.expanduser("~/Downloads/para-realocar")
# Troca as barras para manter o padrão visual do Windows caso necessário, embora o Python lide bem com ambas
WORK_DIR = os.path.normpath(WORK_DIR)
os.makedirs(WORK_DIR, exist_ok=True)
os.chdir(WORK_DIR)

# =============================
# Interface e Estética
# =============================

def exibir_ascii_animado(ascii_art: str, duracao: float = 3.0, fps: int = 20):
    """
    Exibe a ASCII Art com um degradê de cores aleatórias 
    animado da esquerda para a direita.
    """
    lines = ascii_art.strip("\n").splitlines()
    frames = int(duracao * fps)
    
    # Sorteia frequências e fases para gerar paletas RGB dinâmicas e aleatórias
    r_f = random.uniform(0.05, 0.15)
    g_f = random.uniform(0.05, 0.15)
    b_f = random.uniform(0.05, 0.15)
    r_p = random.uniform(0, 6.28)
    g_p = random.uniform(0, 6.28)
    b_p = random.uniform(0, 6.28)

    # Imprime linhas vazias para criar espaço no terminal sem apagar o histórico
    sys.stdout.write("\n" * len(lines))
    sys.stdout.flush()

    # Loop de animação
    for frame in range(frames):
        # Move o cursor do terminal para cima para sobrescrever a arte frame a frame
        sys.stdout.write(f"\033[{len(lines)}A\r")
        
        offset = frame * 2.0  # Define a velocidade que o degradê desliza
        
        for line in lines:
            linha_colorida = ""
            for col_idx, char in enumerate(line):
                # Pula o cálculo se for espaço em branco para manter a performance
                if char == " ":
                    linha_colorida += " "
                    continue

                # Calcula a cor baseada na coluna e no tempo (frame)
                idx = col_idx - offset
                r = int(math.sin(r_f * idx + r_p) * 127 + 128)
                g = int(math.sin(g_f * idx + g_p) * 127 + 128)
                b = int(math.sin(b_f * idx + b_p) * 127 + 128)
                
                # Aplica a cor RGB ao caractere específico
                linha_colorida += f"\033[38;2;{r};{g};{b}m{char}"
            
            # Reseta a cor no final da linha e quebra
            sys.stdout.write(linha_colorida + "\033[0m\n")
        
        sys.stdout.flush()
        time.sleep(1.0 / fps)

ascii_logo = r"""
 ▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄
 █                                                                            █
 █       _  __ ____   __    _____                                             █
 █      | |/ // __ \ / /   / ___/                                             █
 █      |   // /_/ // /    \__ \                                              █
 █     /   |/ _, _// /___ ___/ /                                              █
 █    /_/|_/_/ |_|/_____//____/                                               █
 █        ___    ____  ______ __  __ ____ _    __ ______                      █
 █       /   |  / __ \/ ____// / / //  _/| |  / // ____/                      █
 █      / /| | / /_/ / /    / /_/ / / /  | | / // __/                         █
 █     / ___ |/ _, _/ /___ / __  /_/ /   | |/ // /___                         █
 █    /_/  |_/_/ |_|\____//_/ /_//___/   |___//_____/                         █
 █                                                                            █
 █────────────────────────────────────────────────────────────────────────────█
 █                 . : P R O U D L Y   P R E S E N T S : .                    █
 █────────────────────────────────────────────────────────────────────────────█
 █                                                                            █
 █   > CRIADOR.: xrlsmkl                                                      █
 █   > Capas, legendas e conversão                                            █
 █   > VERSAO..: Junho 2026                                                   █
 █                                                                            █
 ▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀
"""

# =============================
# Execução de subprocessos
# =============================

def print_stage(stage: str, percent: Optional[float] = None, color: str = Color.CYAN, end: str = "\r"):
    if percent is None:
        msg = f"{color}{stage}{Color.RESET}"
    else:
        msg = f"{color}{stage}: {percent:6.2f}%{Color.RESET}"
    print(msg, end=end, flush=True)

def eprintln(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)

def run(cmd: List[str], capture: bool = True, check: bool = True) -> subprocess.CompletedProcess:
    # No Windows, shell=True não é necessário para listar comandos se estiverem no PATH,
    # mas resolve alguns problemas de chamadas em arquivos com espaços.
    return subprocess.run(cmd, check=check, text=True, capture_output=capture)

def run_ffmpeg_with_progress(cmd: List[str], total_duration: float, stage_label: str) -> bool:
    cmd_with_progress = [
        cmd[0],
        "-hide_banner",
        "-nostats",
        "-progress", "pipe:1",
    ] + cmd[1:]
    try:
        proc = subprocess.Popen(
            cmd_with_progress,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
        )
    except FileNotFoundError:
        eprintln(f"{Color.RED}FFmpeg não encontrado. Instale o FFmpeg no Windows e adicione-o às Variáveis de Ambiente (PATH).{Color.RESET}")
        return False

    last_percent = -1.0
    try:
        while True:
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    break
                continue
            line = line.strip()

            if line.startswith("out_time_ms="):
                val = line.split("=", 1)[1]
                try:
                    elapsed = int(val) / 1_000_000.0
                    percent = (elapsed / total_duration) * 100.0 if total_duration > 0 else 0.0
                    percent = min(100.0, percent)
                    if percent - last_percent >= 0.5:
                        print_stage(stage_label, percent, color=Color.GREEN)
                        last_percent = percent
                except ValueError:
                    continue

            elif line.startswith("progress=") and line.split("=",1)[1] == "end":
                print_stage(stage_label, 100.0, color=Color.GREEN)
                print()
    finally:
        ret = proc.wait()
        if ret != 0:
            print()
            eprintln(f"{Color.RED}Erro na etapa '{stage_label}'.{Color.RESET}")
            return False
    return True

# =============================
# FFprobe e metadata
# =============================

def ffprobe_json(input_path: str, select_streams: Optional[str] = None, entries: Optional[str] = None) -> dict:
    cmd = ["ffprobe","-v","error","-print_format","json"]
    if select_streams:
        cmd += ["-select_streams", select_streams]
    if entries:
        cmd += ["-show_entries", entries]
    else:
        cmd += ["-show_format","-show_streams"]
    cmd.append(input_path)
    cp = run(cmd)
    return json.loads(cp.stdout)

def get_duration_seconds(input_path: str) -> float:
    data = ffprobe_json(input_path, entries="format=duration")
    try:
        return float(data["format"]["duration"])
    except Exception:
        return 0.0

def list_subtitle_streams(input_path: str) -> List[dict]:
    data = ffprobe_json(input_path, select_streams="s",
                        entries="stream=index,codec_name,disposition:stream_tags=language,title")
    streams = data.get("streams", []) or []
    for i, st in enumerate(streams):
        st["s_index"] = i
    return streams

# =============================
# Encoding legendas
# =============================

def detect_encoding_fallback(path: str) -> str:
    # No Windows, tentamos UTF-8 primeiro, depois Latin-1/cp1252
    try:
        with open(path, "r", encoding="utf-8") as f:
            f.read()
        return "utf-8"
    except:
        return "latin-1"

def ensure_utf8(legenda_path: str) -> str:
    enc = detect_encoding_fallback(legenda_path)
    if enc.lower().replace("-", "") == "utf8":
        return legenda_path
    new_path = os.path.splitext(legenda_path)[0] + ".utf8.srt"
    try:
        with open(legenda_path, "r", encoding=enc, errors="replace") as f:
            content = f.read()
        with open(new_path, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        print(f"{Color.YELLOW}Convertido '{legenda_path}' ({enc}) → '{new_path}'{Color.RESET}")
        return new_path
    except Exception as e:
        eprintln(f"{Color.RED}Falha converter '{legenda_path}': {e}{Color.RESET}")
        return legenda_path

# =============================
# TMDB + pôster + capa
# =============================

TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/original"

def http_get_json(url: str, params: dict) -> dict:
    q = urllib.parse.urlencode(params)
    context = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(f"{url}?{q}", context=context) as resp:
        return json.loads(resp.read().decode())

def http_download_file(url: str, dst_path: str) -> None:
    # Download direto garantido
    with urllib.request.urlopen(url) as resp, open(dst_path, "wb") as f:
        f.write(resp.read())

def parse_title_year(name: str) -> Tuple[str, Optional[int]]:
    """Separa título e ano de um nome (sem extensão). Aceita 'Matrix_1999', 'Matrix 1999' ou só 'Matrix'."""
    name = name.strip()
    m = re.match(r"(.+?)[_\s]+((?:19|20)\d{2})$", name)
    if m:
        return m.group(1).replace("_", " ").strip(), int(m.group(2))
    return name.replace("_", " ").strip(), None

def extract_title_year_from_filename(path: str) -> Tuple[str, Optional[int]]:
    base = os.path.splitext(os.path.basename(path))[0]
    # remove sufixos que o próprio script adiciona durante o processamento
    base = re.sub(r"(_(convertido|final|cover|utf8))+$", "", base, flags=re.IGNORECASE)
    return parse_title_year(base)

def get_tmdb_api_key_interactive() -> Optional[str]:
    k = os.environ.get("TMDB_API_KEY", "")
    return k.strip() if k else None

def tmdb_search_movie(api_key: str, title: str, year: Optional[int]) -> Optional[dict]:
    params = {"api_key": api_key, "query": title, "language": "pt-BR", "include_adult": "true"}
    if year:
        params["year"] = year
    try:
        data = http_get_json("https://api.themoviedb.org/3/search/movie", params)
    except Exception as e:
        eprintln(f"{Color.RED}Erro TMDB search: {e}{Color.RESET}")
        return None
    return (data.get("results") or [None])[0]

def tmdb_fetch_posters(api_key: str, movie_id: int) -> List[dict]:
    try:
        data = http_get_json(f"https://api.themoviedb.org/3/movie/{movie_id}/images", {
            "api_key": api_key, "language": "en-US", "include_image_language": "pt,en,null"
        })
    except Exception as e:
        eprintln(f"{Color.RED}Erro TMDB images: {e}{Color.RESET}")
        return []
    return data.get("posters") or []

def download_posters(posters: List[dict]) -> List[str]:
    saved = []
    for i, p in enumerate(posters[:10]): # Limita aos 10 primeiros
        fpath = p.get("file_path")
        if not fpath: continue
        url = f"{TMDB_IMAGE_BASE}{fpath}"
        out = os.path.join(WORK_DIR, f"poster_{i:02d}.jpg")
        try:
            http_download_file(url, out)
            saved.append(out)
            print(f"Poster baixado: {out} ({p.get('width')}x{p.get('height')})")
        except Exception as e:
            eprintln(f"{Color.RED}Falha baixar {url}: {e}{Color.RESET}")
    return saved

def embed_cover_with_progress(video_path: str, cover_path: str) -> Optional[str]:
    base, ext = os.path.splitext(video_path)
    tmp = f"{base}_cover{ext}"
    cmd = [
        "ffmpeg", "-y", "-i", video_path, "-i", cover_path,
        "-map", "0", "-map", "1", "-c", "copy",
        "-disposition:v:1", "attached_pic",
        tmp
    ]
    total = get_duration_seconds(video_path)
    ok = run_ffmpeg_with_progress(cmd, total, "Embutindo pôster")
    if ok:
        os.replace(tmp, video_path)
        return video_path
    return None

def aplicar_capa_local(video_path: str) -> bool:
    """Embute uma imagem local. Retorna True se deu certo."""
    img_path = input("Caminho/Nome do arquivo de imagem (ex: capa.jpg): ").strip().strip('"')
    if not img_path:
        print(f"{Color.YELLOW}Nenhum arquivo informado.{Color.RESET}")
        return False

    # Resolve o caminho para garantir que ache na pasta atual ou caminho absoluto
    img_full = os.path.join(WORK_DIR, img_path) if not os.path.isabs(img_path) else img_path
    if not os.path.exists(img_full):
        print(f"{Color.RED}Arquivo de imagem não encontrado: {img_full}{Color.RESET}")
        return False

    return embed_cover_with_progress(video_path, img_full) is not None

def aplicar_capa_tmdb(video_path: str, titulo_manual: Optional[str] = None) -> Optional[bool]:
    """
    Busca e aplica a capa via TMDB.
    Retorna: True = capa aplicada | False = falhou (não achou, sem pôster, erro) | None = você pulou de propósito.
    """
    api_key = get_tmdb_api_key_interactive()
    if not api_key:
        return False

    if titulo_manual:
        title, year = parse_title_year(titulo_manual)
    else:
        title, year = extract_title_year_from_filename(video_path)

    print(f"\nTítulo: '{title}' | Ano: {year or 'desconhecido'}")
    movie = tmdb_search_movie(api_key, title, year)
    if not movie or not movie.get("id"):
        print(f"{Color.YELLOW}Filme não encontrado no TMDB.{Color.RESET}")
        return False

    posters = tmdb_fetch_posters(api_key, movie["id"])
    if not posters:
        print(f"{Color.YELLOW}Nenhum pôster disponível.{Color.RESET}")
        return False

    saved = download_posters(posters)
    if not saved:
        return False

    print("\nPôsteres disponíveis:")
    for i, f in enumerate(saved):
        print(f" [{i}] {os.path.basename(f)}")

    def limpar():
        for f in saved:
            try: os.remove(f)
            except: pass

    idx_in = input("\nEscolha um pôster (número) ou Enter para pular: ").strip()
    if not idx_in:
        limpar()
        return None  # pulou de propósito

    try:
        idx = int(idx_in)
    except ValueError:
        print(f"{Color.YELLOW}Opção inválida.{Color.RESET}")
        limpar()
        return False

    if not (0 <= idx < len(saved)):
        print(f"{Color.YELLOW}Número fora da lista.{Color.RESET}")
        limpar()
        return False

    res = embed_cover_with_progress(video_path, saved[idx])
    limpar()
    return res is not None

def escolher_e_aplicar_capa(video_path: str) -> None:
    print(f"\n{Color.CYAN}--- Adicionar Capa ---{Color.RESET}")
    print("1 - Usar arquivo de imagem local")
    print("2 - Buscar no TMDB (Padrão)")

    escolha = input("Escolha uma opção [1/2] (Padrão: 2): ").strip()

    if escolha == "1":
        resultado: Optional[bool] = aplicar_capa_local(video_path)
    else:
        resultado = aplicar_capa_tmdb(video_path)

    # Se falhou, não sai do fluxo: oferece alternativas até dar certo ou você pular
    while resultado is False:
        print(f"\n{Color.YELLOW}Não foi possível adicionar a capa.{Color.RESET}")
        print("1 - Tentar de novo com outro nome (TMDB)")
        print("2 - Usar uma capa já baixada (imagem local)")
        print("3 - Pular (continuar sem capa)")
        opc = input("Escolha uma opção [1/2/3] (Padrão: 1): ").strip()

        if opc == "3":
            print(f"{Color.YELLOW}Seguindo sem capa.{Color.RESET}")
            return
        elif opc == "2":
            resultado = aplicar_capa_local(video_path)
        else:
            nome = input("Novo nome para a busca (ex: Other Mommy 2026) [Enter volta ao menu]: ").strip()
            if not nome:
                continue
            resultado = aplicar_capa_tmdb(video_path, nome)

# =============================
# Funções principais
# =============================

def extrair_legendas_interativamente(input_path: str) -> List[str]:
    streams = list_subtitle_streams(input_path)
    if not streams:
        print("Não há legendas para extrair.")
        return []

    resp = input("Deseja extrair legendas embutidas? (s/n) ").strip().lower()
    if resp not in {"s", "sim", "y", "yes"}:
        return []

    print("Legendas encontradas:")
    for st in streams:
        lang = st.get("tags", {}).get("language", "und")
        title = st.get("tags", {}).get("title", "")
        codec = st.get("codec_name", "?")
        print(f"  [{st['s_index']}] codec={codec}, lang={lang}, title='{title}'")

    choice = input("Quais extrair? ex: 'todas' ou '0,2,3': ").strip().lower()
    if choice in {"todas", "all", "*"}:
        to_extract = [st["s_index"] for st in streams]
    else:
        try:
            to_extract = [int(x.strip()) for x in choice.split(",") if x.strip()]
        except:
            return []

    extracted = []
    for sidx in to_extract:
        st = next((x for x in streams if x["s_index"] == sidx), None)
        if not st: continue
        lang = st.get("tags", {}).get("language", "und")
        movie_name = os.path.splitext(os.path.basename(input_path))[0]
        out = os.path.join(WORK_DIR, f"{movie_name}_{lang}_{sidx}.srt")

        cmd = ["ffmpeg", "-y", "-i", input_path, "-map", f"0:s:{sidx}", out]
        try:
            run(cmd)
            print(f"{Color.GREEN}Legenda {sidx} extraída → {out}{Color.RESET}")
            extracted.append(out)
        except:
            eprintln(f"{Color.RED}Falha na extração {sidx}{Color.RESET}")
    return extracted

def converter_para_mp4(input_path: str) -> Optional[str]:
    if input_path.lower().endswith(".mp4"):
        return input_path

    out = os.path.join(WORK_DIR, os.path.splitext(os.path.basename(input_path))[0] + "_convertido.mp4")
    total = get_duration_seconds(input_path)
    print(f"Convertendo → {out}")
    cmd = ["ffmpeg", "-y", "-i", input_path, "-c:v", "copy", "-c:a", "aac", "-map", "0:v", "-map", "0:a?", out]

    if run_ffmpeg_with_progress(cmd, total, "Convertendo para MP4"):
        return out
    return None

def adicionar_legendas_externas(mp4_path: str) -> Optional[str]:
    ans = input("Deseja adicionar legendas externas? (s/n): ").strip().lower()
    if ans not in {"s", "sim", "y"}: return mp4_path

    try:
        n = int(input("Quantas legendas externas? ").strip())
    except: return mp4_path
    
    legends = []
    for i in range(n):
        lp = input(f"Caminho/Nome da legenda {i+1}: ").strip()
        if not os.path.exists(os.path.join(WORK_DIR, lp)):
            lp_full = os.path.join(WORK_DIR, lp)
            if not os.path.exists(lp_full):
                print("Arquivo não encontrado.")
                continue
        lang = input(f"Idioma da legenda {i+1} (ex: por, eng): ").strip() or "und"
        utf8leg = ensure_utf8(lp)
        legends.append((utf8leg, lang))

    if not legends: return mp4_path

    final = os.path.splitext(mp4_path)[0] + "_final.mp4"
    cmd = ["ffmpeg","-y","-i",mp4_path]
    for leg, _ in legends:
        cmd += ["-i", leg]
    
    cmd += ["-c:v","copy","-c:a","copy","-c:s","mov_text","-map","0:v","-map","0:a?"]
    for i, (_, lang) in enumerate(legends):
        cmd += ["-map", f"{i+1}:s:0", f"-metadata:s:s:{i}", f"language={lang}"]
    
    cmd += ["-disposition:s:0","default", final]
    
    total = get_duration_seconds(mp4_path)
    if run_ffmpeg_with_progress(cmd, total, "Adicionando legendas"):
        return final
    return mp4_path

# =============================
# Loop Principal
# =============================

def main():
    exibir_ascii_animado(ascii_logo, duracao=3.0, fps=25)
    while True:
        print(f"\n{Color.CYAN}--- Novo Processamento ---{Color.RESET}")
        
        # 1. Pergunta o arquivo de origem
        arq = input("Nome do vídeo original na pasta (ou 'sair'): ").strip()
        if arq.lower() == "sair": break
        
        arq_full = os.path.join(WORK_DIR, arq)
        if not os.path.exists(arq_full):
            print(f"{Color.RED}Arquivo não existe em {WORK_DIR}{Color.RESET}")
            continue

        # Pergunta se o usuário quer apenas adicionar uma capa
        resp_capa = input("Deseja APENAS adicionar uma capa a este arquivo? (s/n): ").strip().lower()
        apenas_capa = resp_capa in {"s", "sim", "y", "yes"}

        # 2. Pergunta o nome final desejado
        nome_final = input("Qual será o nome final do filme para a busca do pôster? (ex: Matrix_1999) [Deixe em branco para manter o atual]: ").strip()

        if apenas_capa:
            # --- FLUXO 1: APENAS ADICIONAR CAPA ---
            arquivo_trabalho = arq_full
            
            # Se forneceu um nome final, vamos renomear antes de buscar a capa para ajudar o scraper do TMDB
            if nome_final:
                ext = os.path.splitext(arq_full)[1]
                if not nome_final.lower().endswith(ext):
                    nome_final += ext
                
                novo_caminho = os.path.join(WORK_DIR, nome_final)
                if arquivo_trabalho != novo_caminho:
                    try:
                        os.rename(arquivo_trabalho, novo_caminho)
                        arquivo_trabalho = novo_caminho
                        print(f"{Color.GREEN}Arquivo renomeado para: {os.path.basename(arquivo_trabalho)}{Color.RESET}")
                    except Exception as e:
                        eprintln(f"{Color.RED}Erro ao renomear: {e}{Color.RESET}")
            
            # Aplica a capa e encerra esse ciclo
            escolher_e_aplicar_capa(arquivo_trabalho)
            print(f"\n{Color.GREEN}✓ PROCESSO CONCLUÍDO (Apenas Capa): {arquivo_trabalho}{Color.RESET}")
            continue

        # --- FLUXO 2: PROCESSAMENTO NORMAL (COMPLETO) ---
        extrair_legendas_interativamente(arq_full)
        
        arq_mp4 = converter_para_mp4(arq_full)
        if not arq_mp4: continue

        final = adicionar_legendas_externas(arq_mp4)
        
        # 3. Renomeia o arquivo gerado para o nome final antes de aplicar a capa
        if nome_final:
            if not nome_final.lower().endswith('.mp4'):
                nome_final += '.mp4'
            novo_caminho = os.path.join(WORK_DIR, nome_final)
            
            if final != novo_caminho:
                try:
                    os.rename(final, novo_caminho)
                    final = novo_caminho
                    print(f"{Color.GREEN}Arquivo renomeado para: {os.path.basename(final)}{Color.RESET}")
                except Exception as e:
                    eprintln(f"{Color.RED}Erro ao renomear para o nome final: {e}{Color.RESET}")

        # Aplica a capa
        escolher_e_aplicar_capa(final)
        print(f"\n{Color.GREEN}✓ PROCESSO CONCLUÍDO: {final}{Color.RESET}")

if __name__ == "__main__":
    main()