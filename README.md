# gamedev-final-project

## How to run

### Requirements

- Python 3.12 (tested on 3.12.10). Download it from [python.org](https://www.python.org/downloads/) or install it on macOS with `brew install python@3.12`.

### 1. Get the code

Clone the repo, or download it with **Code → Download ZIP** on GitHub and unzip it.

```bash
git clone https://github.com/Suhrab-R/gamedev-final-project.git
cd gamedev-final-project
```

### 2. Set up a virtual environment (first time only)

The virtual environment keeps the game's packages separate from everything else on your computer, so the versions can't conflict.

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Windows (PowerShell)**

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If PowerShell says running scripts is disabled, run this once and then try again:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`
