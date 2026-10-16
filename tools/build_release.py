"""Build the Windows release zip: dist/Notarius-<version>.zip

Layout inside the zip (what the user sees after "Extract All"):

  Notarius-<version>/
    Instalar Notarius.cmd     double-click to install or update
    LEIA-ME.txt               the same in plain words
    app/                      the program (copied to %LOCALAPPDATA%\\Notarius)

    uv run python tools/build_release.py
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_FILES = [
    "pyproject.toml", "uv.lock", "README.md", "README.pt-BR.md", "LICENSE",
    "LICENSE.pt-BR.md", "THIRD_PARTY_NOTICES.md", ".python-version",
]
APP_DIRS = ["src", "windows"]

LEIA_ME = """\
NOTARIUS {version}
Transcrição de reuniões com reconhecimento de vozes, tudo no seu computador.

COMO INSTALAR
1. Se ainda não fez: clique com o botão direito no arquivo .zip e escolha
   "Extrair tudo". (Instalar de dentro do .zip não funciona.)
2. Abra a pasta extraída e dê dois cliques em "Instalar Notarius".
3. O Windows pode mostrar "O Windows protegeu o computador". Isso acontece
   porque o instalador não tem assinatura paga. Clique em
   "Mais informações" e depois em "Executar assim mesmo".
4. Uma janela preta mostra o andamento. A instalação baixa cerca de 5 GB e
   pode levar de 15 minutos a uma hora. Se a internet cair, rode de novo:
   ela continua de onde parou.
5. No fim, aparece o atalho "Notarius" na área de trabalho.

COMO ATUALIZAR
Baixe o .zip da versão nova e faça a mesma coisa. Suas transcrições, vozes
e os modelos já baixados são mantidos.

ONDE FICAM AS COISAS
- Suas transcrições e vozes: pasta "Notarius" dentro da sua pasta de usuário.
- O programa e os modelos: %LOCALAPPDATA%\\Notarius
Nada é enviado para a internet.

COMO DESINSTALAR
Menu Iniciar → Notarius → "Desinstalar o Notarius".

Mais informações: https://github.com/pedrotspinola/notarius
"""


def version() -> str:
    text = (ROOT / "src" / "notarius" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__ = "([^"]+)"', text).group(1)


def main() -> None:
    ver = version()
    top = f"Notarius-{ver}"
    out = ROOT / "dist" / f"{top}.zip"
    out.parent.mkdir(exist_ok=True)
    files: list[tuple[Path, str]] = [(ROOT / f, f"{top}/app/{f}") for f in APP_FILES]
    for d in APP_DIRS:
        for p in sorted((ROOT / d).rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts:
                files.append((p, f"{top}/app/{p.relative_to(ROOT).as_posix()}"))
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.write(ROOT / "windows" / "Instalar Notarius.cmd", f"{top}/Instalar Notarius.cmd")
        z.writestr(f"{top}/LEIA-ME.txt",
                   LEIA_ME.format(version=ver).replace("\n", "\r\n").encode("utf-8-sig"))
        for src, arc in files:
            z.write(src, arc)
    print(f"{out} ({out.stat().st_size / 1e6:.1f} MB, {len(files) + 2} files)")


if __name__ == "__main__":
    main()
