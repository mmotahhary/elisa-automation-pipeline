"""
project_setup.py
Run once to create the ELISA project folder structure and requirements file.
"""

import os
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))

folders = [
    r"config",
    r"notebooks",
    r"hamilton",
    r"data\input",
    r"data\output",
    r"data\flags",
    r"reports",
    r"logs",
    r"tests",
    r"database",
]

print(f"Setting up project under: {ROOT}\n")

for folder in folders:
    path = os.path.join(ROOT, folder)
    os.makedirs(path, exist_ok=True)
    print(f"  {path}")

# README
readme_path = os.path.join(ROOT, "README.txt")
with open(readme_path, "w") as f:
    f.write("ELISA Automation Project\n")
    f.write(f"Created : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    f.write("Author  : M. Motahhary\n")
    f.write("Purpose : Full ELISA pipeline simulation\n")

# requirements.txt
requirements = """\
pandas
numpy
scipy
matplotlib
requests
pytest
jupyter
notebook
reportlab
"""

req_path = os.path.join(ROOT, "requirements.txt")
with open(req_path, "w") as f:
    f.write(requirements)

print(f"\nREADME.txt and requirements.txt written.")
print(f"\nInstall dependencies:\n  pip install -r {req_path}")
