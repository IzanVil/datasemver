# Tutorial: la limpieza que cambió la respuesta

A un equipo de datos le dan el listado de pasajeros del Titanic y le piden que lo deje
presentable para un informe. Hacen cuatro cosas sensatas:

- quitar `Cabin`, que está vacía en el 77 % de las filas
- rellenar las edades que faltan con la mediana, para que los gráficos dejen de tener huecos
- redondear `Fare` a unidades enteras, porque nadie cita una tarifa con cuatro decimales
- acotar el informe a primera y segunda clase, que es de lo que iba

Cada decisión es defendible. Juntas producen un dataset donde la tasa de supervivencia es del
**56 %** en lugar del **38 %**, y nada en la lista de columnas lo dice.

Este recorrido lleva unos cinco minutos y no necesita cuenta, ni servicio, ni más datos de
ejemplo que un fichero público.

> Este tutorial también está [en inglés](https://github.com/IzanVil/datasemver/blob/main/docs/tutorial.md).

## Preparar el terreno

```bash
pip install datasemver
curl -o passengers_v1.csv \
  https://raw.githubusercontent.com/datasciencedojo/datasets/master/titanic.csv
```

Son 891 filas y 12 columnas. Ahora genera la versión aseada, que es la «v2» que habría escrito
un pipeline:

```python
# clean.py
import pandas as pd

d = pd.read_csv("passengers_v1.csv")
d = d.drop(columns=["Cabin"])                   # vacía al 77 %
d["Age"] = d["Age"].fillna(d["Age"].median())   # rellenar los huecos
d["Fare"] = d["Fare"].round(0).astype(int)      # redondear las tarifas
d = d[d["Pclass"] != 3]                         # el informe va de 1ª y 2ª
d.to_csv("passengers_v2.csv", index=False)
```

```bash
python clean.py
```

## Preguntar qué ha pasado

```bash
datasemver diff passengers_v1.csv passengers_v2.csv --current-version 1.2.0
```

La entrada de changelog que imprime es lo que merece leerse:

```markdown
## [2.0.0] - 2026-09-08

### Major
- Row count fell from 891 to 400 (-55.11%)
- Column 'Cabin' was removed
- Column 'Survived' distribution moved (KS 0.250): mean 0.3838 -> 0.5575, std 0.4863 -> 0.4967
- Column 'Pclass' distribution moved (KS 0.750): mean 2.309 -> 1.46, std 0.8356 -> 0.4984
- Column 'Age' distribution moved (KS 0.155): mean 29.7 -> 33.57, std 14.52 -> 14.31
- Column 'Parch' distribution moved (KS 0.250): mean 0.3816 -> 0.3675, std 0.8056 -> 0.691
- Column 'Fare' changed type from float64 to int64
- Column 'Fare' distribution moved (KS 0.306): mean 32.2 -> 54.96, std 49.67 -> 66.23

### Minor
- Column 'Embarked' balance shifted (PSI 0.164): 'Q' 8.7% -> 1.3%

### Patch
- Column 'PassengerId' mean moved from 446 to 454.4 (1.88%)
- Column 'Age' nulls dropped from 19.9% to 0.0%
- Column 'SibSp' mean moved from 0.523 to 0.41 (21.61%)
```

De `1.2.0` pasa a `2.0.0`, y el motivo no es que haya desaparecido una columna.

> La herramienta imprime en inglés, así que las salidas de esta página aparecen tal cual las
> devuelve. Traducirlas sería inventar lo que verás en tu terminal.

## Leer la respuesta

**`Survived` pasó de 0.3838 a 0.5575.** Esta es la línea que importa. Quien calcule una tasa de
supervivencia sobre la v2 obtiene un 56 % donde la v1 decía 38 %, y ninguna comprobación de
esquema lo habría detectado: la columna sigue ahí, se llama igual y sigue siendo un número. Se
movió porque se filtró la tercera clase, que es donde estaban casi todas las muertes. El filtro
iba de alcance; el efecto fue sobre la respuesta.

**`Embarked` es un minor, no un major.** Todos los puertos que había siguen ahí —el conjunto de
categorías no cambia—, pero Queenstown pasó del 8,7 % de los pasajeros al 1,3 %. Una
comparación de los valores distintos no ve nada. El Population Stability Index ve 0,164, que es
la franja entre «conviene saberlo» y «ya no es la misma población».

**`Age` recibe dos hallazgos de severidad distinta.** Que sus nulos bajen del 19,9 % a cero es
`patch`: el dataset dice lo mismo que decía, con menos huecos. Que su distribución se mueva es
`major`, porque rellenar un quinto de una columna con un único valor no es un acto neutro.
Ambas cosas son ciertas a la vez, y la más fuerte fija el salto.

**Redondear `Fare` es de por sí un cambio de tipo que rompe.** De `float64` a `int64` es un
estrechamiento, no un ensanchamiento: toda tarifa que tuviera decimales deja de ir y volver
igual, y el código que dividía por ella pasa a hacer división entera. Al revés —de `int64` a
`float64`— habría sido un patch. La dirección es toda la diferencia.

**`PassengerId` se reporta como patch y puedes ignorarlo**, que es justo para lo que sirve que
sea un patch en vez de un silencio. Es un identificador; su media no significa nada. Un fichero
de reglas puede decirlo, y la siguiente sección lo hace.

## Rechazarlo

Enterarse después vale menos que no publicarlo. `--fail-on` convierte el informe en una puerta:

```bash
datasemver diff passengers_v1.csv passengers_v2.csv --fail-on major
```

```
refused: suggested bump is major, which reaches the --fail-on threshold of major
```

```bash
echo $?   # 1
```

Tres códigos de salida, para que un pipeline pueda distinguirlos: `0` se ejecutó y no había
nada que rechazar, `1` se ejecutó y el salto alcanzó el umbral, `2` no pudo ejecutarse. La
misma bandera funciona en la
[GitHub Action](https://github.com/IzanVil/datasemver/blob/main/.github/workflows/datasemver.yml),
donde el rechazo llega después del comentario que lo explica.

### Decir a qué columnas te referías

Que `PassengerId` derive es ruido, y también lo es el número de filas si el informe *tiene que*
estrecharse. Un fichero de reglas dice cuál es cuál:

```yaml
# report-rules.yaml
major:
  - column_removed
  - distribution_shift: {columns: [Survived, Fare]}
minor:
  - distribution_shift
  - category_balance_shift
ignore:
  - minor_stat_change: {columns: [PassengerId]}
```

```bash
datasemver diff passengers_v1.csv passengers_v2.csv --rules report-rules.yaml
```

Las dos columnas de las que va el informe conservan su severidad; el resto baja un escalón; el
identificador se reporta y no cuenta para nada:

```
MAJOR  column_removed          Column 'Cabin' was removed
MAJOR  distribution_shift      Column 'Survived' distribution moved (KS 0.250)
MAJOR  distribution_shift      Column 'Fare' distribution moved (KS 0.306)
MINOR  distribution_shift      Column 'Pclass' distribution moved (KS 0.750)
MINOR  distribution_shift      Column 'Age' distribution moved (KS 0.155)
MINOR  category_balance_shift  Column 'Embarked' balance shifted (PSI 0.164)
—      minor_stat_change       Column 'PassengerId' mean moved from 446 to 454.4
```

`ignore` no es silencio. El cambio se sigue detectando y se sigue imprimiendo; se deja sin
clasificar para que no contribuya al salto. «Esto se esperaba» y «no ha pasado nada» son
respuestas distintas, y solo una es cierta.

## Qué filas, no solo qué forma

Todo lo anterior compara perfiles. Dale una clave y compara filas:

```bash
datasemver diff passengers_v1.csv passengers_v2.csv --key PassengerId
```

```
0 row(s) added and 491 removed, matched on the key
266 of 400 row(s) present in both changed value (66.5%): Fare (248), Age (41)
```

Dos tercios de las filas que sobrevivieron al filtro cambiaron además de valor — algo que el
número de filas por sí solo nunca podría haberte dicho, porque solo bajó.

## Guardar la respuesta sin guardar los datos

Una comparación lee un perfil, y un perfil es pequeño:

```bash
datasemver profile passengers_v1.csv
```

```
profile written passengers_v1.profile.json (12 columns, 891 rows, 6211 bytes)
```

6 KB frente a 60 KB aquí; sobre un Parquet de 63 MB son 2,9 KB. Guárdalo junto al dataset y la
siguiente comparación solo necesita la versión nueva:

```bash
datasemver diff passengers_v1.profile.json passengers_v3.csv
```

El fichero que describe ya no tiene por qué existir. Eso es lo que hace que esto funcione contra
un dataset demasiado grande para guardar dos copias, o contra uno que vive en un almacén que
solo puedes consultar.

## Por dónde seguir

- [El catálogo de reglas](https://github.com/IzanVil/datasemver/blob/main/docs/rules.md) — todas las reglas, métricas y umbrales (en inglés)
- [El README](https://github.com/IzanVil/datasemver/blob/main/README.es.md) — bases de datos, libros de Excel, DVC, el panel y la API de Python
- `datasemver rules` — imprime el conjunto de reglas exactamente como lo entendió el motor, que es la forma más rápida de comprobar que un fichero de reglas hace lo que querías
