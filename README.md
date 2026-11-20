# XRLS Archive

Processador de filmes para o terminal: converte vídeos para **MP4**, embute ou extrai **legendas**
e adiciona **capa** (pôsteres do TMDB), tudo em uma única passada do FFmpeg.

- Todas as perguntas vêm no começo; depois é só esperar a fila terminar
- Nome sugerido a partir do nome do arquivo (`The.Matrix.1999.1080p…` → `the_matrix_1999`; para manter maiúsculas e espaços, desligue `nome_minusculo` no `config.json`)
- Galeria de pôsteres no navegador para escolher olhando
- Legendas externas detectadas na pasta, com conversão automática para UTF-8
- **Legendas online**: busca no OpenSubtitles pelo hash do arquivo, pelo ID do TMDB ou pelo nome, e sincroniza com o áudio (alass ou ffsubsync, opcionais)
- Funciona no **Windows**, **Debian/Ubuntu**, macOS

## Instalação

### Debian / Ubuntu
```bash
git clone https://github.com/carlmnm/xrls-archive-processor.git
cd xrls-archive-processor
./install-debian.sh
xrls
```

### Windows
```powershell
winget install Gyan.FFmpeg
winget install Python.Python.3.12
git clone https://github.com/carlmnm/xrls-archive-processor.git
cd xrls-archive-processor
python processor6.py
```
Feche e reabra o terminal depois de instalar o FFmpeg.

## Uso

```
python3 processor6.py                      modo interativo
python3 processor6.py filme.mkv outro.avi  processa direto (no Windows, dá para arrastar os arquivos sobre o script)
python3 processor6.py --legenda filme.mkv  só baixa a legenda, sincroniza e salva ao lado do vídeo (Nome.pob.srt)
python3 processor6.py --setup              reconfigura as chaves (TMDB, OpenSubtitles) e as preferências
python3 processor6.py --dir ~/Videos       usa outra pasta de trabalho
```

Na primeira execução o programa pede sua chave gratuita do TMDB
(<https://www.themoviedb.org/settings/api>) e guarda em
`~/.config/xrls/config.json` (Linux) ou `%APPDATA%\xrls\config.json` (Windows).
Também é aceita a variável de ambiente `TMDB_API_KEY`.

### Legendas online (opcional)
Crie uma chave gratuita ("API consumer") no site opensubtitles.com e cadastre com `--setup`
(ou use a variável `OPENSUBTITLES_API_KEY`). Cada pessoa usa a própria chave.
Para alinhar a legenda baixada ao áudio, instale o [alass](https://github.com/kaegi/alass) ou o `ffsubsync`
(`pip install ffsubsync`); sem eles a legenda entra como veio. Quando o OpenSubtitles garante que a legenda
confere com o arquivo (hash), a sincronização é dispensada.

Pasta de trabalho padrão: `~/Downloads/para-realocar`.

## Versões

- `processor6.py` — versão atual (Windows, Linux, macOS)
- `legacy/processor5.py` — versão anterior, mantida só como histórico (a chave do TMDB agora vem de `TMDB_API_KEY`)

## Licença

MIT
