<div align="center">

# DataSemver

**Tus datos han cambiado. DataSemver te dice si eso es un patch, un minor o una versión que rompe.**

[![Tests](https://github.com/IzanVil/datasemver/actions/workflows/tests.yml/badge.svg)](https://github.com/IzanVil/datasemver/actions/workflows/tests.yml)
[![Coverage](https://codecov.io/gh/IzanVil/datasemver/branch/main/graph/badge.svg)](https://codecov.io/gh/IzanVil/datasemver)
[![PyPI](https://img.shields.io/pypi/v/datasemver.svg)](https://pypi.org/project/datasemver/)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](https://github.com/IzanVil/datasemver/blob/main/LICENSE)

[English](https://github.com/IzanVil/datasemver/blob/main/README.md) · **Español**

</div>

DataSemver compara dos versiones de un dataset CSV, JSON o Parquet, clasifica cada
diferencia que encuentra según un conjunto de reglas configurable, y devuelve el salto de
versión semántica junto con una entrada de changelog lista para commitear. Es una CLI
primero y una librería de Python después, y no necesita registro de esquemas, ni base de
datos, ni ningún servicio corriendo.

<p align="center">
  <img src="https://raw.githubusercontent.com/IzanVil/datasemver/main/docs/assets/cli-diff.png" width="880"
       alt="Terminal con datasemver diff: un salto MAJOR de 0.0.0 a 1.0.0, una tabla de columnas que marca country como añadida, phone como modificada y legacy_code como eliminada, una tabla que clasifica siete cambios por severidad, y la entrada de changelog generada.">
</p>

<p align="center">
  <sub><code>datasemver diff tests/fixtures/old.csv tests/fixtures/new.csv</code> — una columna eliminada
  y un <code>int64</code> convertido en <code>string</code> hacen de esto una versión que rompe.</sub>
</p>

---

## Índice

- [Por qué](#por-qué)
- [Instalación](#instalación)
- [Inicio rápido](#inicio-rápido)
- [Demo](#demo)
- [Versionado semántico para datos](#versionado-semántico-para-datos)
- [Referencia de comandos](#referencia-de-comandos)
- [Configuración: reglas en YAML](#configuración-reglas-en-yaml)
- [API de Python](#api-de-python)
- [GitHub Action](#github-action)
- [Panel web](#panel-web)
- [Estructura del proyecto](#estructura-del-proyecto)
- [Changelog](#changelog)
- [Contribuir](#contribuir)
- [Licencia](#licencia)

## Por qué

El código tiene SemVer y los datos no. Una columna eliminada, un número de teléfono que se
convirtió en cadena, una distribución que se desplazó en silencio: todo eso rompe a los
consumidores aguas abajo, y todo eso suele publicarse como «se actualizó el dataset».
DataSemver hace ese impacto explícito y revisable, para que la publicación de un dataset se
pueda discutir igual que la de una librería.

## Instalación

Desde PyPI:

```bash
pip install datasemver
```

Como comando independiente, sin tocar tu entorno:

```bash
pipx install datasemver
```

Desde el código fuente, para desarrollar o para levantar el panel:

```bash
git clone https://github.com/IzanVil/datasemver.git
cd datasemver
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

| Extra | Instala | Para |
| --- | --- | --- |
| _(ninguno)_ | `pandas`, `pyarrow`, `pydantic`, `pyyaml`, `typer`, `rich` | La librería y el comando `datasemver` |
| `dev` | `pytest`, `pytest-cov`, `httpx` | Ejecutar los tests y medir la cobertura |
| `web` | `fastapi`, `uvicorn`, `python-multipart` | El [panel web](#panel-web) |

```bash
pip install "datasemver[web]"
```

Requiere Python 3.10 o superior. El paquete se distribuye tipado (`py.typed`), así que los
verificadores de tipos ven las anotaciones de cada función pública.

## Inicio rápido

```bash
pip install datasemver
datasemver diff old.csv new.csv --current-version 1.4.2
```

Eso imprime el panel, la comparación de columnas y los cambios clasificados que se ven
arriba, y sale con `0`. No escribe nada salvo que se lo pidas.

<details>
<summary>La misma ejecución como texto seleccionable</summary>

```
╭───────────── DataSemver ──────────────╮
│ Suggested bump: MAJOR                 │
│ 0.0.0 -> 1.0.0                        │
│                                       │
│ old: tests/fixtures/old.csv (8 rows)  │
│ new: tests/fixtures/new.csv (10 rows) │
╰───────────────────────────────────────╯
                                    Columns
┏━━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━┓
┃ column      ┃ status    ┃ type old ┃ type new ┃ nulls         ┃ cardinality ┃
┡━━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━┩
│ country     │ added     │ -        │ string   │ - -> 0.0%     │ - -> 4      │
│ age         │ modified  │ int64    │ int64    │ 0.0% -> 0.0%  │ 8 -> 10     │
│ email       │ modified  │ string   │ string   │ 25.0% -> 0.0% │ 6 -> 10     │
│ phone       │ modified  │ int64    │ string   │ 0.0% -> 0.0%  │ 8 -> 10     │
│ score       │ modified  │ float64  │ float64  │ 0.0% -> 0.0%  │ 8 -> 10     │
│ legacy_code │ removed   │ string   │ -        │ 0.0% -> -     │ 8 -> -      │
│ id          │ unchanged │ int64    │ int64    │ 0.0% -> 0.0%  │ 8 -> 10     │
│ name        │ unchanged │ string   │ string   │ 0.0% -> 0.0%  │ 8 -> 10     │
└─────────────┴───────────┴──────────┴──────────┴───────────────┴─────────────┘
                                        Changes
┏━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ severity ┃ rule                      ┃ description                                   ┃
┡━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ MAJOR    │ column_removed            │ Column 'legacy_code' was removed              │
│ MAJOR    │ type_changed_incompatible │ Column 'phone' changed type from int64 to     │
│          │                           │ string                                        │
│ MINOR    │ row_count_increased       │ Row count grew from 8 to 10 (+25.00%)         │
│ MINOR    │ column_added              │ Column 'country' was added                    │
│ PATCH    │ nulls_fixed               │ Column 'email' nulls dropped from 25.0% to    │
│          │                           │ 0.0%                                          │
│ PATCH    │ minor_stat_change         │ Column 'age' mean moved from 37.12 to 38.2    │
│          │                           │ (2.90%)                                       │
│ PATCH    │ minor_stat_change         │ Column 'score' mean moved from 72.47 to 71.22 │
│          │                           │ (1.72%)                                       │
└──────────┴───────────────────────────┴───────────────────────────────────────────────┘
```

</details>

Sin `--output`, la entrada de changelog se imprime al final de la ejecución:

```markdown
## [1.0.0] - 2026-09-02

### Major
- Column 'legacy_code' was removed
- Column 'phone' changed type from int64 to string

### Minor
- Row count grew from 8 to 10 (+25.00%)
- Column 'country' was added

### Patch
- Column 'email' nulls dropped from 25.0% to 0.0%
- Column 'age' mean moved from 37.12 to 38.2 (2.90%)
- Column 'score' mean moved from 72.47 to 71.22 (1.72%)
```

Puedes integrarlo en un script de release leyendo el salto desde la salida JSON:

```bash
BUMP=$(datasemver diff old.csv new.csv --json | jq -r '.bump')
datasemver diff old.csv new.csv --current-version "$(cat VERSION)" --output CHANGELOG.md
```

## Demo

En [`demo.cast`](https://github.com/IzanVil/datasemver/blob/main/demo.cast) hay una grabación de la CLI que se reproduce en local:

```bash
pip install asciinema
asciinema play demo.cast
```

Vuelve a grabarla tras un cambio en la salida de la CLI, y súbela para obtener un
reproductor compartible:

```bash
asciinema rec demo.cast --overwrite --cols 90 --rows 40
asciinema upload demo.cast
```

## Versionado semántico para datos

El salto de versión es la severidad más alta encontrada entre todos los cambios
detectados. Qué significa «más alta» lo define por completo el fichero de reglas, pero los
valores por defecto siguen la lectura de abajo.

| Salto | Significado para los consumidores | Disparadores por defecto |
| --- | --- | --- |
| **Major** | Las consultas y pipelines existentes pueden romperse | Columna eliminada o renombrada, cambio de tipo incompatible (`int64` → `string`), desplazamiento de la distribución de al menos 0,5 σ, pérdida de más del 20% de las filas, más de 10 puntos de nulos introducidos |
| **Minor** | Información nueva, los contratos existentes se mantienen | Columna añadida, filas añadidas, filas eliminadas por debajo del umbral de major, categoría nueva o eliminada, cambio de cardinalidad, nulos introducidos por debajo del umbral de major |
| **Patch** | El mismo significado, mejores datos | Nulos rellenados, deriva estadística pequeña, ampliación de tipo compatible (`int64` → `float64`) |

Los cambios que ninguna regla cubre siguen apareciendo en el informe como *unclassified* y
nunca inflan el salto. Si no coincide nada, la versión se deja intacta.

Lo que DataSemver mira:

- **Esquema** — columnas añadidas, eliminadas y renombradas, cambios de dtype, nulabilidad.
- **Contenido** — número de filas, cardinalidad, media y desviación típica de las columnas
  numéricas, moda y conjunto de categorías de las categóricas.
- **Semántica** — columnas renombradas, inferidas a partir de la similitud tanto del nombre
  de la columna como de sus valores, de modo que `user_name` → `username` se reporta como
  un renombrado y no como una eliminación más una adición.

## Referencia de comandos

```bash
datasemver diff OLD NEW [OPTIONS]
datasemver rules [RULES_FILE]
python -m datasemver diff OLD NEW     # equivalente, sin necesidad de instalar
```

| Opción | Corta | Descripción |
| --- | --- | --- |
| `--rules PATH` | `-r` | Fichero de reglas que sustituye a las incluidas por defecto |
| `--current-version TEXT` | `-c` | Versión desde la que se salta el dataset nuevo (por defecto `0.0.0`) |
| `--output PATH` | `-o` | Escribe la entrada de changelog en un fichero, anteponiéndola si ya existe |
| `--json` | | Imprime el informe completo como JSON en lugar de las tablas |

Ejemplos:

```bash
datasemver diff old.json new.json --current-version 1.4.2
datasemver diff snapshots/2026-08.parquet snapshots/2026-09.parquet
datasemver diff old.csv new.csv --rules examples/strict_rules.yaml
datasemver diff old.csv new.csv --output CHANGELOG.md
datasemver diff old.csv new.csv --json | jq '.classified[] | {severity, rule: .rule}'
datasemver rules examples/lenient_rules.yaml
```

Los formatos se detectan por extensión: `.csv`, `.tsv`, `.json`, `.jsonl`, `.ndjson`,
`.parquet` y `.pq`. El delimitador de un `.csv` se detecta a partir de sus primeras líneas
—se reconocen coma, punto y coma, tabulador y barra vertical, y un carácter que solo
aparece dentro de valores entrecomillados no gana—, mientras que `.tsv` siempre usa el
tabulador. Define `DATASEMVER_CSV_DELIMITER` para saltarte la detección y forzar un único
carácter, incluido el tabulador, escrito como `\t`; también tiene prioridad sobre el
tabulador de un `.tsv`, y un valor vacío equivale a no definirlo. Los objetos JSON anidados
y los structs de Parquet se aplanan con un separador `.`, de modo que
`{"user": {"name": "..."}}` se perfila como la columna `user.name`. El comando sale con `2`
si falta el fichero, la extensión no está soportada, el dataset no se puede leer o el
fichero de reglas es inválido.

<p align="center">
  <img src="https://raw.githubusercontent.com/IzanVil/datasemver/main/docs/assets/cli-delimiter.png" width="880"
       alt="Terminal con datasemver diff sobre dos CSV separados por punto y coma: cinco columnas correctamente separadas en id, cliente, pais, importe y estado, una columna canal nueva, y un salto MINOR de 1.4.2 a 1.5.0.">
</p>

<p align="center">
  <sub>Una exportación separada por punto y coma, donde cada <code>importe</code> contiene además
  una coma. La coma nunca llega a la cabecera, así que gana el punto y coma y el fichero se
  carga como cinco columnas en lugar de una.</sub>
</p>

Los tipos se infieren en los formatos de texto, donde una columna de valores `"12"` se lee
como `int64`. Parquet lleva su propio esquema y se respeta tal cual, así que una columna
almacenada como cadena sigue siendo cadena aunque todos los valores parezcan numéricos.
Comparar un CSV contra la exportación a Parquet de los mismos datos está soportado y
reporta los mismos cambios:

```bash
datasemver diff tests/fixtures/old.csv tests/fixtures/new.parquet
```

## Configuración: reglas en YAML

Cada severidad es una lista de reglas. El motor evalúa `major`, luego `minor` y luego
`patch`, y la primera regla que casa con un cambio le asigna su severidad:

```yaml
major:
  - column_removed
  - type_changed_incompatible
  - row_count_decrease_greater_than: 20

minor:
  - column_added
  - row_count_decreased

patch:
  - nulls_fixed
  - minor_stat_change
```

Pásalo con `--rules custom.yaml` para sustituir los valores por defecto, y comprueba cómo
se ha interpretado con `datasemver rules custom.yaml`, que imprime el conjunto de reglas tal
y como lo ha entendido el motor:

<p align="center">
  <img src="https://raw.githubusercontent.com/IzanVil/datasemver/main/docs/assets/cli-rules.png" width="760"
       alt="Terminal con datasemver rules: el conjunto de reglas por defecto impreso en tres grupos de severidad con color, seis reglas en major, siete en minor y tres en patch.">
</p>
 Las reglas con umbral como
`row_count_decrease_greater_than` se emparejan de forma natural con su equivalente sin
umbral en una severidad inferior, que entonces actúa como respaldo. Los nombres de regla
desconocidos, las severidades desconocidas y los umbrales sobre reglas que no los aceptan
se rechazan con un error en lugar de ignorarse.

El catálogo completo de reglas, métricas y umbrales está en [docs/rules.md](https://github.com/IzanVil/datasemver/blob/main/docs/rules.md)
(en inglés). En [`examples/`](https://github.com/IzanVil/datasemver/tree/main/examples) se incluyen dos perfiles listos para usar:
`strict_rules.yaml` y `lenient_rules.yaml`.

## API de Python

```python
from datasemver import analyze

report = analyze("old.csv", "new.csv", current_version="1.4.2")

print(report.bump)          # Severity.MAJOR
print(report.next_version)  # 2.0.0

for item in report.classified:
    print(item.severity, item.rule, item.change.description)
```

`analyze_schemas()` recibe dos perfiles ya cargados, así que se pueden comparar dataframes
que vengan de cualquier sitio sin tocar el sistema de ficheros:

```python
import pandas as pd
from datasemver.core.analyzer import analyze_schemas
from datasemver.formats.loader import schema_from_frame

report = analyze_schemas(
    schema_from_frame(pd.read_sql(query, engine), "warehouse@yesterday"),
    schema_from_frame(pd.read_sql(query, engine), "warehouse@today"),
)
```

## GitHub Action

[`.github/workflows/datasemver.yml`](https://github.com/IzanVil/datasemver/blob/main/.github/workflows/datasemver.yml) ejecuta DataSemver
en cada pull request y publica el resultado como comentario. Compara cada dataset que toca
la rama contra su versión en la rama base, y reescribe el mismo comentario en cada push en
lugar de ir apilando comentarios nuevos.

```
## DataSemver report

Suggested bump for this branch: **MAJOR**

| Dataset                | Current | Suggested | Bump  | Changes |
| ---------------------- | ------- | --------- | ----- | ------- |
| `data/customers.csv`   | 1.4.2   | **2.0.0** | MAJOR | 7       |
| `data/users.json`      | 0.0.0   | **0.1.0** | MINOR | 3       |

<details><summary><code>data/customers.csv</code> — 7 classified change(s)</summary>

- **MAJOR** (`column_removed`): Column 'legacy_code' was removed
- **MAJOR** (`type_changed_incompatible`): Column 'phone' changed type from int64 to string
- **MINOR** (`row_count_increased`): Row count grew from 8 to 10 (+25.00%)
- … and 4 more

</details>
```

El trabajo ocurre en [`scripts/run_datasemver_on_pr.py`](https://github.com/IzanVil/datasemver/blob/main/scripts/run_datasemver_on_pr.py),
así que el workflow queda como un envoltorio fino y el mismo análisis se puede lanzar a
mano:

```bash
python scripts/run_datasemver_on_pr.py --base-ref origin/main --output report.md
```

| Opción | Descripción |
| --- | --- |
| `--base-ref` | Ref que contiene la versión anterior de cada dataset (por defecto `origin/main`) |
| `--head-ref` | Ref contra el que comparar la base; por defecto, el árbol de trabajo |
| `--paths` | Analiza estos datasets en lugar de detectar los que han cambiado |
| `--rules` | Fichero de reglas que se pasa a `datasemver diff` |
| `--default-version` | Versión asumida cuando un dataset no tiene fichero adjunto de versión |
| `--top-changes` | Cambios listados por dataset (por defecto 5) |
| `--output` | Escribe el informe en Markdown en este fichero |

Expone `has_report`, `max_bump` y `dataset_count` como salidas del step, escribe el informe
en el resumen del job, y siempre sale con `0`: una rama sin cambios en datasets, un dataset
añadido por primera vez, un fichero ilegible o un ref base que falta se reportan en lugar
de hacer fallar el job.

### Versiones de los datasets

La versión actual de un dataset se lee de un fichero adjunto commiteado junto a él, de modo
que cada dataset lleva su propia versión:

```
data/customers.csv
data/customers.csv.version   # contiene 1.4.2
```

Sin ese fichero, el análisis parte de `--default-version` (`0.0.0`). El salto es
deliberado: el comentario te dice la versión que el dataset merece, y tú la escribes en el
fichero adjunto en el mismo pull request.

### Usarlo en otro repositorio

Copia ambos ficheros en el repositorio destino e instala DataSemver desde PyPI en lugar de
usar la copia local:

```yaml
name: DataSemver

on:
  pull_request:
    types: [opened, synchronize, reopened]

permissions:
  contents: read
  pull-requests: write

jobs:
  analyse:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install datasemver
      - id: datasemver
        run: |
          python scripts/run_datasemver_on_pr.py \
            --base-ref "origin/${{ github.base_ref }}" \
            --rules .datasemver/rules.yaml \
            --output "${{ runner.temp }}/report.md"
      - if: steps.datasemver.outputs.has_report == 'true'
        uses: actions/github-script@v7
        env:
          REPORT_PATH: ${{ runner.temp }}/report.md
        with:
          script: |
            const fs = require('fs');
            const body = fs.readFileSync(process.env.REPORT_PATH, 'utf8');
            const { owner, repo } = context.repo;
            await github.rest.issues.createComment({
              owner,
              repo,
              issue_number: context.issue.number,
              body,
            });
```

`fetch-depth: 0` es obligatorio: sin el historial completo, la versión base del dataset no
está en el clon. El `GITHUB_TOKEN` por defecto basta siempre que el job declare
`pull-requests: write`.

Dos límites que conviene conocer. Los pull requests abiertos desde un fork reciben un token
de solo lectura, así que para ellos se omite el paso del comentario; el informe sigue
estando en el resumen del job. Y un dataset lo bastante grande como para estar guardado en
Git LFS necesita `lfs: true` en el paso de checkout, o si no la versión base será un
fichero puntero en lugar de datos.

## Panel web

En [`datasemver_web/`](https://github.com/IzanVil/datasemver/tree/main/datasemver_web) viven un backend FastAPI y un frontend
sin dependencias. Sube dos
versiones de un dataset, o elige dos versiones de un directorio, y lee en el navegador el
salto, los cambios clasificados, la comparación de columnas y la entrada de changelog.

Viaja dentro del paquete, así que no hace falta clonar nada:

```bash
pip install "datasemver[web]"
uvicorn datasemver_web.backend.main:app
```

Desde un clon, `pip install -r requirements-web.txt` y añade `--reload`.

Después abre <http://127.0.0.1:8000>; el backend sirve el frontend, así que ese es el único
comando. La vista de histórico escanea `./datasets/` por defecto, agrupando ficheros
llamados `customers_v1.csv`, `customers_v2.csv` y así sucesivamente.

<p align="center">
  <img src="https://raw.githubusercontent.com/IzanVil/datasemver/main/docs/assets/dashboard-report.png" width="880"
       alt="El panel tras comparar dos versiones de un dataset de clientes: una insignia MAJOR junto a 1.4.2 flecha 2.0.0, indicadores de 40 a 48 filas, 8 a 8 columnas y 6 cambios, y una tabla con cada cambio, su severidad, su regla y su descripción.">
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/IzanVil/datasemver/main/docs/assets/dashboard-columns.png" width="880"
       alt="Más abajo en el mismo informe: una tabla de columnas que marca country como añadida, legacy_code como eliminada y phone como modificada de int64 a string, con nulos y cardinalidad de cada una, y debajo la entrada de changelog generada con un botón de copiar.">
</p>

<p align="center">
  <sub>La misma comparación que imprime la CLI, leída en el navegador: primero el salto y los
  cambios clasificados, después la tabla columna a columna y la entrada de changelog lista
  para copiar.</sub>
</p>

El panel es un cliente de la librería, no una copia bifurcada: llama a `analyze()` y
devuelve el mismo informe que imprime la CLI con `--json`.

```bash
curl -X POST http://127.0.0.1:8000/api/diff \
  -F "old=@tests/fixtures/old.csv" \
  -F "new=@tests/fixtures/new.csv" \
  -F "current_version=1.4.2"
```

Los endpoints, la configuración y la convención de nombres de los datasets están
documentados en [datasemver_web/README.md](https://github.com/IzanVil/datasemver/blob/main/datasemver_web/README.md) (en inglés).

## Estructura del proyecto

```
datasemver/
├── core/
│   ├── analyzer.py       cargar, comparar, clasificar, versionar
│   ├── changelog.py      renderizado del changelog y escritura en fichero
│   ├── differ.py         comparación de dos perfiles de dataset
│   └── models.py         modelos pydantic compartidos por el pipeline
├── formats/
│   ├── loader.py         lectores de CSV, JSON y Parquet
│   └── utils.py          inferencia de tipos y perfilado de columnas
├── rules/
│   ├── engine.py         parseo de reglas y asignación de severidad
│   └── default_rules.yaml
├── utils/
│   ├── similarity.py     heurísticas de detección de renombrados
│   └── version.py        aritmética de versiones semánticas
└── cli/main.py           punto de entrada de typer

CHANGELOG.md              las versiones del propio proyecto
docs/rules.md             catálogo de reglas
examples/                 perfiles de reglas alternativos
scripts/                  ayudante de CI que analiza los datasets que toca una rama
web/                      backend FastAPI y frontend estático del panel
datasets/                 datasets versionados de ejemplo para el histórico del panel
.github/workflows/        análisis de pull requests, matriz de tests y publicación
tests/                    suite de pytest y fixtures de datasets
demo.cast                 grabación de asciinema usada en la demo de arriba
```

## Changelog

Cada versión publicada está descrita en [CHANGELOG.md](https://github.com/IzanVil/datasemver/blob/main/CHANGELOG.md), que usa el mismo
vocabulario que la herramienta aplica a los datasets: **Major** para cambios que rompen
aquello de lo que ya dependen los consumidores, **Minor** para capacidad nueva que deja
intactos los contratos existentes, **Patch** para arreglos que mantienen el mismo
significado.

## Contribuir

Las issues y los pull requests son bienvenidos. Empieza por [CONTRIBUTING.md](https://github.com/IzanVil/datasemver/blob/main/CONTRIBUTING.md)
(en inglés) para el entorno de desarrollo, el flujo de tests y el estilo que se espera en un
parche. Se espera que todo el mundo que participe siga el
[Código de Conducta](https://github.com/IzanVil/datasemver/blob/main/CODE_OF_CONDUCT.md).

```bash
pip install -e ".[dev]"
pytest
```

## Licencia

MIT. Ver [LICENSE](https://github.com/IzanVil/datasemver/blob/main/LICENSE).
