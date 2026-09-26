# 🃏 Arlequin SaveHub

**Gestor automático de partidas guardadas y copias de seguridad para juegos de PC en Windows.**

Arlequin SaveHub es una aplicación de escritorio que detecta los juegos instalados en el sistema, identifica sus ubicaciones de guardado y permite crear y restaurar copias de seguridad de forma controlada.

A diferencia de los gestores que intentan localizar partidas buscando indiscriminadamente en carpetas genéricas como `Documents`, `AppData` o `Saved Games`, Arlequin SaveHub utiliza información específica del juego para determinar **qué título está instalado y dónde debe encontrarse su partida**.

El sistema combina la detección de instalaciones mediante diferentes plataformas y lanzadores con una **base de datos centralizada de identificadores y ubicaciones de saves**, permitiendo resolver las rutas de guardado de cada juego de forma reproducible.

> **Detectar → Identificar → Resolver → Respaldar → Restaurar**

---

## Características principales

* Detección automática de juegos instalados.
* Soporte para:

  * Steam
  * Epic Games Store
  * GOG
  * Battle.net
  * Ubisoft Connect
  * juegos instalados fuera de un launcher
* Identificación mediante identificadores de plataforma cuando están disponibles.
* Resolución de rutas de guardado mediante una base de datos centralizada.
* Soporte para diferentes ubicaciones de Windows:

  * `%APPDATA%`
  * `%LOCALAPPDATA%`
  * `Documents`
  * carpetas de instalación
  * directorios dependientes del usuario de la plataforma
* Resolución de rutas mediante plantillas y condiciones específicas de plataforma.
* Detección de partidas existentes y de ubicaciones previstas que todavía no existen.
* Creación de backups.
* Restauración de backups.
* Rotación de copias anteriores.
* Verificación de backups.
* Soporte para instalaciones portables o sin launcher.
* Añadir manualmente carpetas de partidas.
* Ocultar juegos del listado.
* Diagnóstico de detección y resolución de rutas.
* Actualización de la base de datos desde GitHub.
* Comprobación de actualizaciones de la aplicación.
* Registro de operaciones mediante logs.

---

# Arquitectura

Arlequin SaveHub separa la información sobre los juegos de la lógica encargada de gestionarlos.

La arquitectura puede resumirse en dos componentes principales:

```text
┌──────────────────────────────┐
│       Arlequin SaveHub       │
│                              │
│  Detección / Gestión / GUI   │
└───────────────┬──────────────┘
                │
                │ consulta
                ▼
┌──────────────────────────────┐
│  id_y_ubicacion_saves.yaml   │
│                              │
│  Identificadores             │
│  Rutas de guardado           │
│  Condiciones por plataforma  │
└──────────────────────────────┘
```

La aplicación contiene la lógica necesaria para detectar instalaciones y administrar los archivos, mientras que el YAML actúa como un **catálogo de conocimiento sobre los juegos**.

Esto permite ampliar la compatibilidad añadiendo o modificando entradas de la base de datos sin tener que implementar una búsqueda específica para cada juego.

---

# ¿Cómo funciona?

## 1. Detección de juegos instalados

La aplicación obtiene información de las plataformas instaladas en el equipo.

Dependiendo del launcher, la detección utiliza los registros y archivos que cada plataforma mantiene localmente.

El proceso contempla actualmente:

### Steam

Se consulta la instalación de Steam, sus bibliotecas y los manifiestos de aplicaciones para determinar qué juegos están instalados.

Además, se obtienen los identificadores de usuario necesarios para resolver rutas que dependen de `userdata`.

### Epic Games Store

La aplicación utiliza los datos locales de instalación de Epic para identificar los juegos instalados y sus ubicaciones.

### GOG

La detección utiliza la información disponible en el sistema para localizar las instalaciones de GOG.

### Battle.net

Se buscan las instalaciones conocidas de los juegos de Blizzard/Battle.net y se identifican sus directorios correspondientes.

### Ubisoft Connect

Se utilizan los directorios e información local del launcher para detectar sus juegos instalados.

### Instalaciones sin launcher

También existe soporte para juegos que no están gestionados por ninguno de los launchers anteriores.

Estas carpetas pueden configurarse desde la aplicación y sus subdirectorios pueden tratarse como instalaciones independientes.

---

# 2. Identificación del juego

Una vez detectada una instalación, Arlequin intenta relacionarla con una entrada de la base de datos.

La identificación utiliza preferentemente los identificadores proporcionados por las plataformas:

```yaml
ids:
  steam: 525480
```

También pueden existir identificadores adicionales:

```yaml
ids:
  steam: 3768760
  steamExtra:
    - 3950810
    - 3950820
```

y referencias para otras plataformas:

```yaml
ids:
  steam: 1000
  gog: 2000
  lutris: example-game
```

Cuando no existe un identificador suficientemente preciso, el sistema puede recurrir al nombre del juego y realizar una comparación aproximada controlada.

La intención es evitar que una coincidencia parcial entre nombres termine asociando una instalación con una entrada incorrecta.

---

# 3. Resolución de la ubicación del save

La base de datos contiene una o varias ubicaciones posibles para cada juego.

Por ejemplo:

```yaml
- name: '.hack//G.U. Last Recode'
  ids:
    steam: 525480
    steamExtra:
      - 746970
  save_locations:
    - <root>/userdata/<storeUserId>/525480/remote/savedata [os=windows, store=steam]
```

La ruta no se almacena necesariamente como una ruta absoluta.

En su lugar se utilizan **plantillas**, que posteriormente se transforman en una ruta real del sistema.

Entre los elementos soportados se encuentran conceptos como:

```text
<root>
<storeUserId>
<winAppData>
<winLocalAppData>
<winDocuments>
<home>
<base>
```

También pueden existir condiciones asociadas a una ruta:

```text
[os=windows]
[store=steam]
[store=epic]
```

Esto permite que una misma entrada de la base de datos describa diferentes escenarios sin introducir lógica específica dentro del programa.

---

# 4. Estados de detección

La aplicación no considera que un juego tenga únicamente dos estados —encontrado o no encontrado—.

El proceso distingue diferentes situaciones.

### Save localizado

El juego está instalado y la ruta definida por la base de datos existe realmente en el equipo.

```text
INSTALADO
   │
   ▼
RUTA RESUELTA
   │
   ▼
CARPETA EXISTENTE
   │
   ▼
SAVE LOCALIZADO
```

### Ruta prevista

El juego está instalado y la aplicación puede resolver correctamente dónde debería encontrarse el save, pero la carpeta todavía no existe.

Esto puede ocurrir, por ejemplo, cuando el juego todavía no se ha ejecutado y aún no ha creado su directorio de partidas.

```text
INSTALADO
   │
   ▼
RUTA RESUELTA
   │
   ▼
CARPETA NO EXISTE
   │
   ▼
RUTA PREVISTA
```

### Sin datos de guardado local

Algunos juegos pueden estar presentes en la base de datos pero no disponer de una partida local que pueda gestionarse.

Por ejemplo, la información disponible puede corresponder únicamente a configuración, registro u otros datos que no constituyen un save local.

### No localizado

El juego ha sido detectado, pero no ha sido posible obtener una ruta de guardado suficientemente fiable.

---

# 5. Gestión de backups

Arlequin SaveHub crea los backups tomando como unidad de respaldo la **carpeta raíz completa del juego**, no únicamente la subcarpeta concreta donde se encuentra el save.

Los backups se almacenan en:

```text
Desktop/
└── Backup Saves/
```

La estructura utilizada dentro de `Backup Saves` refleja la ubicación original del juego. Por ejemplo, si el juego se encuentra en:

```text
C:\Users\Usuario\Documents\My Games\NombreDelJuego\
```

el backup correspondiente se organiza como:

```text
Desktop/
└── Backup Saves/
    └── My Games/
        └── NombreDelJuego/
            └── ...
```

### Backup de la carpeta completa

Cuando una ruta de guardado pertenece a una carpeta raíz de juego, Arlequin SaveHub identifica dicha raíz y respalda **todo su contenido**.

Por ejemplo, si la partida está dentro de:

```text
C:\Users\Usuario\Documents\My Games\Borderlands 2\
└── WillowGame/
    ├── SaveData/
    ├── Config/
    └── Logs/
```

el backup se realiza sobre:

```text
Borderlands 2/
```

y no únicamente sobre:

```text
WillowGame/SaveData/
```

De esta forma, el backup conserva también otros archivos y directorios que formen parte de la instalación o del estado local del juego.

Si varias ubicaciones de guardado detectadas pertenecen a la misma carpeta raíz, la aplicación evita procesarla varias veces y realiza un único backup de dicha raíz.

### Backups históricos

El backup activo mantiene siempre el nombre normal del juego:

```text
Desktop/
└── Backup Saves/
    └── My Games/
        └── NombreDelJuego/
            └── archivos del backup actual
```

Cuando ya existe un backup activo y se genera uno nuevo, la versión anterior **no se sobrescribe directamente**. Primero se archiva como backup histórico:

```text
Desktop/
└── Backup Saves/
    └── My Games/
        ├── NombreDelJuego/
        │   └── archivos del backup actual
        │
        └── NombreDelJuego [DD-MM-YYYY HH-MM-SS]/
            └── archivos del backup anterior
```

El nombre histórico incorpora la fecha y hora asociadas a la operación. Si ya existe un histórico con el mismo nombre, se añade un sufijo para evitar colisiones:

```text
NombreDelJuego [DD-MM-YYYY HH-MM-SS]
NombreDelJuego [DD-MM-YYYY HH-MM-SS] #2
NombreDelJuego [DD-MM-YYYY HH-MM-SS] #3
```

Los directorios históricos se consideran versiones anteriores y no sustituyen al backup activo.

### Proceso de backup

La creación del backup se realiza de forma controlada:

```text
Carpeta raíz del juego
        │
        ▼
Copia a carpeta temporal
        │
        ▼
Verificación de la copia
        │
        ▼
Archivar backup activo anterior
        │
        ▼
Instalar nueva copia como backup activo
```

La nueva copia se prepara primero en una carpeta temporal. Una vez finalizada y verificada, se archiva la versión anterior y la copia temporal pasa a ocupar la ubicación del backup activo.

Si la instalación de la nueva copia falla, la aplicación intenta recuperar el backup anterior. Las carpetas temporales también se eliminan cuando la operación termina con error.

Este procedimiento reduce el riesgo de que una interrupción deje el backup activo en un estado incompleto.

---

# 6. Restauración

La restauración utiliza el mismo concepto que el backup: **se restaura la carpeta raíz completa del juego**, no únicamente la carpeta concreta donde se encuentra el save.

El flujo general es:

```text
Backup seleccionado
       │
       ▼
Copia a carpeta temporal
       │
       ▼
Verificación de la copia
       │
       ▼
Archivar instalación actual
       │
       ▼
Instalar restauración
```

### Origen de la restauración

Normalmente, la restauración utiliza el backup activo:

```text
Backup Saves/
└── My Games/
    └── NombreDelJuego/
```

Si el backup activo ya no existe, Arlequin SaveHub puede localizar automáticamente el **backup histórico más reciente** disponible para esa misma carpeta.

La selección del histórico se realiza utilizando la fecha y hora contenidas en el nombre de la carpeta, no la fecha de modificación del sistema de archivos.

Por ejemplo:

```text
NombreDelJuego [01-09-2026 18-30-00]
NombreDelJuego [15-09-2026 21-10-00]
NombreDelJuego [20-09-2026 09-45-00]
```

En este caso, se seleccionaría el histórico correspondiente al `20-09-2026 09-45-00`.

Si no existe ni un backup activo ni un histórico utilizable, la restauración no puede realizarse para ese juego.

### Conservación de la instalación actual

Antes de reemplazar una carpeta de juego existente, Arlequin SaveHub conserva su contenido completo como una copia histórica.

Por ejemplo, si existe:

```text
Documents/
└── My Games/
    └── NombreDelJuego/
        ├── save.dat
        ├── Config/
        └── ...
```

antes de instalar el backup seleccionado, la carpeta actual se archiva como:

```text
Documents/
└── My Games/
    ├── NombreDelJuego/
    │   └── restauración seleccionada
    │
    └── NombreDelJuego [DD-MM-YYYY HH-MM-SS]/
        └── estado anterior
```

Por tanto, la restauración no utiliza el antiguo sistema de carpetas `_old`. La versión actualmente instalada se conserva mediante una carpeta histórica con fecha y hora.

### Restauración segura

La restauración se prepara primero en una carpeta temporal. La aplicación comprueba que la copia se haya realizado correctamente antes de modificar la instalación existente.

Solo después de superar esa verificación se realiza la sustitución:

1. Se copia el backup completo a una carpeta temporal.
2. Se verifica la copia.
3. Si existe una instalación actual, se archiva con fecha y hora.
4. La copia temporal pasa a ocupar la ubicación original.
5. Si la instalación falla, se intenta restaurar automáticamente la carpeta anterior.

De esta forma, la operación evita sustituir directamente la instalación existente antes de disponer de una copia preparada y verificada.

### Historial de restauraciones y backups

Los históricos cumplen una doble función:

- conservar versiones anteriores de los backups;
- conservar el estado que tenía el juego antes de una restauración.

Por ello, una operación de backup o restauración no tiene por qué eliminar definitivamente el estado anterior del juego.

La estructura puede terminar conteniendo tanto el backup activo como varias versiones históricas:

```text
Backup Saves/
└── My Games/
    ├── NombreDelJuego/
    ├── NombreDelJuego [01-09-2026 18-30-00]/
    ├── NombreDelJuego [15-09-2026 21-10-00]/
    └── NombreDelJuego [20-09-2026 09-45-00]/
```

Esto permite mantener un historial de estados anteriores y utilizar el histórico más reciente como fuente de recuperación cuando el backup activo no está disponible.

---

# 7. Verificación y rotación

Arlequin SaveHub no trata los backups como simples carpetas estáticas.

La aplicación puede:

* comprobar la existencia de backups;
* verificar que no estén vacíos;
* localizar copias históricas;
* conservar versiones anteriores;
* rotar copias cuando se genera una nueva versión;
* registrar las operaciones realizadas.

El objetivo es mantener un historial utilizable sin sobrescribir indiscriminadamente el estado anterior.

---

# Base de datos de juegos

El archivo:

```text
id_y_ubicacion_saves.yaml
```

es una parte fundamental del proyecto.

Contiene la relación entre:

```text
Juego
  │
  ├── Identificadores
  │     ├── Steam
  │     ├── GOG
  │     ├── Lutris
  │     └── otros identificadores
  │
  └── save_locations
        ├── ruta
        ├── plataforma
        └── condiciones
```

A fecha de 26/09/2026 la base de datos contiene 12.191 juegos y permite describirlos con diferentes estructuras de almacenamiento.

Por ejemplo, un mismo juego puede disponer de rutas diferentes dependiendo de si procede de Steam o Epic:

```yaml
save_locations:
  - <ruta-steam> [os=windows, store=steam]
  - <ruta-epic> [os=windows, store=epic]
```

Esto permite que la lógica de detección permanezca separada de la información específica de cada juego.

---

# Actualización de la base de datos

La aplicación puede actualizar la base de datos de juegos desde el repositorio de GitHub.

El archivo utilizado es:

id_y_ubicacion_saves.yaml

La actualización se realiza en segundo plano después de iniciar la interfaz, evitando que la apertura de la aplicación dependa de la descarga de la base de datos.

La aplicación mantiene una copia local del archivo YAML para poder seguir utilizando la base de datos disponible cuando no sea posible realizar una actualización desde GitHub.

Esta copia local contiene la información de identificación y las ubicaciones de guardado de los juegos; no contiene las partidas guardadas ni los backups del usuario.

La base de datos y los backups son elementos independientes:

```text
Base de datos
└── id_y_ubicacion_saves.yaml
    ├── Juegos
    ├── Identificadores
    └── Ubicaciones de saves

Backups
└── Desktop/
    └── Backup Saves/
        └── Copias reales de los archivos de los juegos.
```

---

# Actualizaciones de la aplicación

Arlequin SaveHub también dispone de un mecanismo de comprobación de nuevas versiones.

La versión de la aplicación y la información necesaria para comprobar actualizaciones se gestionan de forma independiente de la base de datos de juegos.

Esto permite actualizar:

```text
Aplicación
     +
Base de datos
```

por separado.

---

# Juegos sin launcher

No todos los juegos de PC están instalados mediante Steam, Epic, GOG, Battle.net o Ubisoft Connect.

Por este motivo, Arlequin SaveHub incorpora soporte para:

* juegos DRM-free;
* instalaciones portables;
* juegos antiguos;
* instalaciones manuales;
* carpetas personalizadas.

Además, el usuario puede añadir manualmente una carpeta cuando el mecanismo automático no dispone de información suficiente para detectar una instalación.

---

# Juegos ocultos

Los juegos detectados automáticamente pueden ocultarse del listado.

Esta función permite mantener la interfaz centrada únicamente en los títulos que el usuario quiere gestionar sin modificar la información de detección ni la base de datos.

---

# Diagnóstico

Cuando un juego no se detecta como se esperaba, la aplicación proporciona información de diagnóstico.

El diagnóstico permite comprobar aspectos como:

* cómo se identificó el juego;
* qué fuente produjo la detección;
* qué entrada de la base de datos se utilizó;
* qué ruta se resolvió;
* si la ruta existe;
* si se trata de una ubicación prevista;
* si el juego carece de datos de guardado local.

Esto facilita identificar si el problema procede de:

```text
Detección de instalación
        ↓
Identificación
        ↓
Coincidencia con la base de datos
        ↓
Resolución de ruta
        ↓
Existencia del save
```

---

# Priorización de detecciones

Un mismo juego puede ser detectado por más de una fuente.

Por ejemplo, una instalación puede aparecer simultáneamente en diferentes mecanismos de detección.

En estos casos, Arlequin utiliza una prioridad basada en la calidad de la información disponible:

```text
Ruta real existente
        ↓
Ruta prevista
        ↓
Juego conocido sin save local
        ↓
Sin coincidencia utilizable
```

De esta manera, una detección con información real sobre la ubicación del save tiene prioridad sobre una detección meramente predictiva.

---

# Exclusiones

El sistema también contempla situaciones que no deben tratarse como una partida local convencional.

Entre ellas se encuentran determinadas carpetas del sistema y juegos cuyo funcionamiento no requiere un save local gestionable.

Esto evita que directorios irrelevantes aparezcan como partidas potenciales.

---

# Interfaz

La aplicación utiliza una interfaz gráfica basada en **Tkinter**.

El objetivo de la interfaz es proporcionar una vista centralizada de:

* juegos instalados;
* partidas detectadas;
* rutas previstas;
* backups disponibles;
* juegos sin datos de guardado local;
* juegos no localizados;
* juegos añadidos manualmente.

La interfaz también integra las operaciones de backup, restauración, diagnóstico y configuración.

---

# Estructura conceptual del proyecto

```text
Arlequin SaveHub
│
├── Detección
│   ├── Steam
│   ├── Epic Games Store
│   ├── GOG
│   ├── Battle.net
│   ├── Ubisoft Connect
│   └── Instalaciones manuales
│
├── Identificación
│   ├── IDs de plataforma
│   ├── Nombres
│   └── Coincidencia aproximada
│
├── Resolución
│   ├── Plantillas de rutas
│   ├── Variables de entorno
│   ├── IDs de usuario
│   └── Condiciones por plataforma
│
├── Gestión
│   ├── Backup
│   ├── Restauración
│   ├── Verificación
│   └── Rotación
│
├── Configuración
│   ├── Juegos ocultos
│   ├── Juegos manuales
│   └── Carpetas sin launcher
│
└── Mantenimiento
    ├── Actualización de base de datos
    ├── Actualización de aplicación
    ├── Diagnóstico
    └── Logs
```

---

# Instalación

## Usuario final

Para utilizar la aplicación como usuario final se recomienda utilizar la versión compilada disponible en los releases del proyecto.

La aplicación está orientada a:

* **Windows**
* juegos de PC
* instalaciones locales de juegos

---

# Ejecución desde código fuente

Para trabajar con el proyecto desde Python:

```bash
git clone https://github.com/loco965/Arlequin-SaveHub.git
cd Arlequin-SaveHub
```

Se requiere:

```text
Python 3.10+
```

El proyecto utiliza, entre otras, las siguientes tecnologías y componentes:

* Python
* Tkinter
* PyYAML
* APIs y registros de Windows
* herramientas nativas de Windows
* `robocopy`

---

# Flujo de ejecución

El flujo principal de la aplicación puede representarse así:

```text
                  ┌───────────────────┐
                  │ Inicio aplicación │
                  └─────────┬─────────┘
                            │
                            ▼
                  ┌───────────────────┐
                  │ Inicializar GUI   │
                  └─────────┬─────────┘
                            │
                            ▼
             ┌────────────────────────────┐
             │ Detectar juegos instalados │
             └──────────────┬─────────────┘
                            │
                            ▼
             ┌────────────────────────────┐
             │ Identificar cada juego     │
             └──────────────┬─────────────┘
                            │
                            ▼
             ┌────────────────────────────┐
             │ Consultar base de datos    │
             └──────────────┬─────────────┘
                            │
                            ▼
             ┌────────────────────────────┐
             │ Resolver save_locations    │
             └──────────────┬─────────────┘
                            │
                            ▼
                 ┌────────────────────┐
                 │ ¿Ruta existe?      │
                 └───────┬─────┬──────┘
                         │     │
                       Sí│     │No
                         │     │
                         ▼     ▼
                    Localizado  Previsto
                         │     │
                         └──┬──┘
                            ▼
                  ┌───────────────────┐
                  │ Gestión de backup │
                  └───────────────────┘
```

La actualización de la base de datos se realiza en segundo plano después de que la interfaz haya comenzado a funcionar.

---

# Seguridad de las operaciones

Las operaciones de backup y restauración utilizan directorios temporales y comprobaciones antes de modificar las partidas existentes.

El objetivo es evitar que una operación parcialmente completada termine sustituyendo directamente el contenido original sin conservar una copia recuperable.

Aun así, **Arlequin SaveHub no debe considerarse un sustituto de una estrategia de backup independiente**. Las partidas importantes deberían conservarse también en una ubicación adicional.

---

# Contribuir

Una de las partes más importantes del proyecto es ampliar y mantener la base de datos de juegos.

Si un juego no está correctamente identificado o su ubicación de guardado no está incluida, puede añadirse o corregirse su entrada en:

```text
id_y_ubicacion_saves.yaml
```

Una entrada típica tiene esta estructura:

```yaml
- name: 'Nombre del juego'
  ids:
    steam: 123456
  save_locations:
    - <winDocuments>/My Games/NombreDelJuego [os=windows]
```

Cuando una plataforma utiliza una ubicación diferente, pueden añadirse condiciones:

```yaml
- name: 'Nombre del juego'
  ids:
    steam: 123456
    gog: 987654
  save_locations:
    - <ruta-steam> [os=windows, store=steam]
    - <ruta-gog> [os=windows, store=gog]
```

Las contribuciones deberían intentar utilizar rutas específicas y verificables en lugar de introducir búsquedas genéricas.

---

# Filosofía del proyecto

Arlequin SaveHub parte de una idea sencilla:

> **Un gestor de partidas debería saber qué juego está gestionando antes de intentar buscar sus archivos.**

En lugar de:

```text
Buscar carpetas conocidas
        ↓
Encontrar archivos
        ↓
Intentar adivinar a qué juego pertenecen
```

Arlequin utiliza el flujo inverso:

```text
Detectar juego instalado
        ↓
Identificarlo
        ↓
Consultar información específica
        ↓
Resolver su ubicación conocida
        ↓
Gestionar el save
```

Esta separación permite reducir las búsquedas heurísticas y hace que la base de datos sea una parte explícita y mantenible del sistema.

---

# Estado del proyecto

El proyecto continúa en desarrollo y la cobertura de juegos depende de la información disponible en la base de datos.

Que un juego no aparezca correctamente no implica necesariamente que no sea compatible: puede ser necesario añadir su identificador o su ubicación de guardado al catálogo.

---

# Requisitos

* Windows
* Python **3.10+** para ejecución desde código fuente
* Acceso a los archivos locales de las plataformas que se quieran detectar
* Permisos suficientes para acceder a las carpetas de partidas correspondientes

---

# Registro y diagnóstico

La aplicación mantiene información de diagnóstico y operaciones mediante:

```text
app.log
```

También utiliza archivos locales para conservar determinadas preferencias y configuraciones, entre ellas:

```text
juegos_ocultos.txt
juegos_manuales.txt
carpetas_sin_launcher.txt
```

La base de datos descargada se conserva localmente para su utilización por la aplicación.

Los datos de aplicación se almacenan además bajo:

```text
%LOCALAPPDATA%\APP GameSaves
```

Los backups de partidas se almacenan por separado en:

```text
Desktop\Backup Saves
```

---

# Tecnologías

| Componente              | Tecnología                               |
| ----------------------- | ---------------------------------------- |
| Lenguaje                | Python                                   |
| Interfaz gráfica        | Tkinter                                  |
| Base de datos de juegos | YAML                                     |
| Parser YAML             | PyYAML                                   |
| Sistema objetivo        | Windows                                  |
| Detección de Steam      | Archivos/manifiestos locales             |
| Detección de Epic       | Datos locales de instalación             |
| Detección de GOG        | Información local/registro               |
| Detección de Battle.net | Instalaciones y rutas conocidas          |
| Detección de Ubisoft    | Datos locales del launcher               |
| Copias de seguridad     | Python + herramientas nativas de Windows |
| Copia de archivos       | `robocopy` cuando corresponde            |
| Actualización de datos  | GitHub / descarga HTTP                   |

---

# Licencia

Consulta la licencia incluida en el repositorio para conocer las condiciones de uso, modificación y distribución del proyecto.

---

# Créditos

Arlequin SaveHub utiliza información de catálogo de juegos y ubicaciones de guardado mantenida en el proyecto.

Las mejoras de compatibilidad dependen especialmente de las contribuciones relacionadas con nuevas entradas, identificadores y rutas de guardado.

---

## Resumen

Arlequin SaveHub es un gestor de partidas basado en **detección + identificación + resolución de rutas**, en lugar de una búsqueda genérica de archivos.

Su funcionamiento puede resumirse en:

```text
┌─────────────┐
│   Detectar  │
└──────┬──────┘
       ▼
┌─────────────┐
│  Identificar│
└──────┬──────┘
       ▼
┌─────────────┐
│   Resolver  │
└──────┬──────┘
       ▼
┌─────────────┐
│   Localizar │
└──────┬──────┘
       ▼
┌─────────────┐
│   Respaldar │
└──────┬──────┘
       ▼
┌─────────────┐
│  Restaurar  │
└─────────────┘
```

**Arlequin SaveHub convierte la gestión de partidas guardadas en un proceso basado en información estructurada sobre cada juego, en lugar de depender exclusivamente de búsquedas heurísticas en el sistema de archivos.**
