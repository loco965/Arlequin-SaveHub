# 🃏 Arlequin SaveHub

**Gestor automático de partidas guardadas y copias de seguridad para juegos de PC en Windows.**

Arlequin SaveHub detecta los juegos instalados en tu sistema, identifica dónde guardan sus partidas y te permite crear y restaurar copias de seguridad de forma segura.

A diferencia de otros gestores, no busca a ciegas en carpetas genéricas (`Documents`, `AppData`, `Saved Games`...). En su lugar, usa una **base de datos propia de identificadores y ubicaciones** (`id_y_ubicacion_saves.yaml`) para saber exactamente qué juego está instalado y dónde debería estar su save.

> **Detectar → Identificar → Resolver → Respaldar → Restaurar**

---

## Novedades en v1.0.1

- Al restaurar, si hay varias copias de un juego (activa + históricas), ahora se puede elegir: la más reciente, cancelar, o seleccionar cuál restaurar.
- Comprobación de permisos al arrancar, para avisar si falta acceso de administrador en vez de fallar a mitad de un backup.
- Corregida la agrupación de saves bajo `Saved Games`, que ahora sigue la misma jerarquía que `My Games`.

---

## Características

- Detección automática de juegos en **Steam, Epic, GOG, Battle.net y Ubisoft Connect**, además de instalaciones sin launcher.
- Identificación por ID de plataforma (con respaldo por nombre cuando no hay ID).
- Resolución de rutas de guardado mediante plantillas (`<home>`, `<winAppData>`, `<storeUserId>`...) y condiciones por SO/tienda.
- Backup y restauración de la **carpeta raíz completa del juego**, no solo del save.
- Backups históricos con fecha y hora (nunca se sobrescribe nada sin archivar antes).
- Selector manual de qué copia restaurar cuando hay varias disponibles.
- Verificación de backups, juegos ocultos, carpetas añadidas manualmente y diagnóstico de detección.
- Actualización automática de la base de datos y comprobación de nuevas versiones de la app.

---

## Cómo funciona

1. **Detección**: se consultan las plataformas instaladas para saber qué juegos hay y dónde.
2. **Identificación**: cada juego se cruza con `id_y_ubicacion_saves.yaml` por su ID (o por nombre si no hay ID).
3. **Resolución**: las plantillas de ruta del YAML se resuelven a carpetas reales del equipo.
4. **Backup**: se copia la carpeta raíz del juego a `Desktop/Backup Saves/<Carpeta>/<Juego>`, respetando la estructura original (p. ej. `My Games/Borderlands 2` o `Saved Games/CD Projekt Red`).
5. **Restauración**: proceso simétrico, con copia a carpeta temporal, verificación, y archivado con fecha de lo que hubiera antes de instalar la copia elegida.

Todo el proceso (backup y restauración) usa carpetas temporales y verifica la copia antes de tocar nada existente, para no dejar nunca un save a medias.

---

## Base de datos de juegos

El archivo [`id_y_ubicacion_saves.yaml`](./id_y_ubicacion_saves.yaml) contiene, por juego: sus IDs de plataforma y sus `save_locations` (rutas con plantillas y condiciones). Actualmente cubre **más de 12.000 juegos**.

Si un juego no se detecta bien, la forma de arreglarlo es añadir o corregir su entrada en este YAML — no hace falta tocar el código de la app.

```yaml
- name: 'Nombre del juego'
  ids:
    steam: 123456
    gog: 987654
  save_locations:
    - <ruta-steam> [os=windows, store=steam]
    - <ruta-gog> [os=windows, store=gog]
```

---

## Instalación

**Usuario final:** descarga el `.exe` desde los [releases](../../releases) del proyecto.

**Desde código fuente:**
```bash
git clone https://github.com/loco965/Arlequin-SaveHub.git
cd Arlequin-SaveHub
```
Requiere **Python 3.10+** y `pyyaml`.

---

## Requisitos

- Windows
- Permisos de escritura en las carpetas de partidas y en `%LOCALAPPDATA%\APP GameSaves`

---

## Contribuir

La forma más útil de contribuir es ampliar `id_y_ubicacion_saves.yaml` con juegos que falten o rutas incorrectas.

---

## Licencia

Consulta el archivo de licencia incluido en el repositorio.
