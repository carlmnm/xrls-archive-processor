# XRLS Archive

Processador de filmes para o terminal: converte vídeos para **MP4**, embute ou extrai **legendas**
e adiciona **capa** (pôsteres do TMDB), tudo em uma única passada do FFmpeg.

- Todas as perguntas vêm no começo; depois é só esperar a fila terminar
- Nome sugerido a partir do nome do arquivo (`The.Matrix.1999.1080p…` → `the_matrix_1999`; para manter maiúsculas e espaços, desligue `nome_minusculo` no `config.json`)
- Galeria de pôsteres no navegador para escolher olhando
- Legendas externas detectadas na pasta, com conversão automática para UTF-8
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
python3 processor6.py --setup              reconfigura a chave do TMDB e as preferências
python3 processor6.py --dir ~/Videos       usa outra pasta de trabalho
```

Na primeira execução o programa pede sua chave gratuita do TMDB
(<https://www.themoviedb.org/settings/api>) e guarda em
`~/.config/xrls/config.json` (Linux) ou `%APPDATA%\xrls\config.json` (Windows).
Também é aceita a variável de ambiente `TMDB_API_KEY`.

Pasta de trabalho padrão: `~/Downloads/para-realocar`.

## Versões

- `processor6.py` — versão atual (Windows, Linux, macOS)
- `legacy/processor5.py` — versão anterior, mantida só como histórico (a chave do TMDB agora vem de `TMDB_API_KEY`)

## Licença

MIT
