# 🃏 Arlequin SaveHub (Beta)

**Arlequin SaveHub** es un gestor automático e inteligente de partidas guardadas (*saves*) y copias de seguridad para tus juegos de PC. 

A diferencia de los gestores tradicionales que buscan a ciegas en carpetas genéricas, **Arlequin SaveHub funciona leyendo los registros reales de tus plataformas de juego instaladas**, cruzando esos datos con una base de datos propia y centralizada en GitHub para resolver de forma exacta la ruta donde cada juego guarda tus datos.

---

## 📦 Guía Detallada de Uso

### 1. Primeros pasos (Instalación básica)
1. Ve a la sección lateral de **[Releases](https://github.com)**.
2. Descarga el archivo ejecutable compilado **`Arlequin SaveHub.exe`** de la versión Beta más reciente.
3. Muévelo a la carpeta que prefieras y ejecútalo. 
4. El programa creará automáticamente dos directorios en tu sistema:
   * Una carpeta llamada **`Backup Saves`** en tu **Escritorio** (aquí se centralizarán todas tus copias de seguridad de forma ordenada por el nombre del juego).
   * Una carpeta interna en `%LOCALAPPDATA%/APP GameSaves` para gestionar la base de datos y tus listas de preferencias sin ensuciar tus directorios personales.

### 2. Gestión del Listado Principal de Juegos
Al abrirse, verás la lista de todos tus juegos instalados detectados que tienen datos de guardado locales.
* **Selección Múltiple:** Puedes seleccionar uno o varios juegos haciendo clic directamente sobre ellos en la lista. Si deseas procesar todo tu catálogo a la vez, utiliza el botón **"Seleccionar Todo el Listado"**.
* **Crear Copias de Seguridad (Backup):** Con los juegos seleccionados, haz clic en **"Respaldar Partidas"**. El programa leerá las carpetas originales y usará la herramienta nativa `robocopy` para clonarlas en tu carpeta del Escritorio. Si ya tenías un respaldo previo de ese juego, el Hub lo moverá automáticamente a una subcarpeta interna llamada `old/` para garantizar que nunca pierdas un historial válido por culpa de un guardado corrupto reciente.
* **Restaurar Partidas (Restore):** Si has formateado tu PC o quieres recuperar un progreso anterior, selecciona el juego y presiona **"Restaurar Partidas"**. El programa tomará los archivos almacenados en tu Escritorio y los inyectará exactamente en las rutas originales del juego. Por seguridad, la partida actual de tu PC se renombrará con el sufijo `_old` antes de la sobreescritura.

### 3. Juegos Portables y Rutas Personalizadas
* **Juegos sin Launcher (DRM-Free / Emuladores):** Si tienes juegos descargados que no usan tiendas (como instalaciones portables de GOG o emuladores), haz clic en el botón de gestión de carpetas raíz sin launcher. Añade el directorio padre donde guardas estos juegos; el programa escaneará sus nombres y buscará sus equivalencias automáticamente en la base de datos descargada de GitHub.
* **Añadir Carpeta Manual:** Si un juego usa una ruta extremadamente rara o modificada que no se detecta de ninguna forma, usa **"Añadir Carpeta Manual"**. Te pedirá que selecciones la carpeta exacta de los *saves* en tu disco y que le asignes un nombre para recordarlo. Aparecerá en tu lista principal al instante.
* **Ocultar Juegos:** Si no te interesa hacer copias de seguridad de ciertos títulos instalados y quieres limpiar tu interfaz, selecciónalos y pulsa **"Ocultar de la Vista"**. El programa los enviará a una lista negra local para no volver a listarlos. Puedes revertir esto en cualquier momento desde el submenú de elementos ocultados.

### 4. Uso del Motor de Diagnóstico
Si notas que un juego instalado no aparece en la lista principal, o quieres comprobar qué rutas exactas está resolviendo el programa:
1. Haz clic en el botón de **"Diagnóstico de Juego"**.
2. Escribe el nombre del juego (completo o una palabra clave aproximada).
3. El script generará en tiempo real un informe técnico detallado que se mostrará en pantalla indicándote:
   * Si el sistema detecta el juego como instalado y a través de qué launcher.
   * La ruta de instalación original registrada en tu Windows.
   * Si el juego está en la lista de exclusiones por ser un software de sistema o un juego 100% online (sin *saves* físicos).
   * Las plantillas de guardado encontradas en el `.yaml` y si esas carpetas existen o no actualmente en tu disco duro.

---

## 🚀 Cómo Funciona por Dentro

Al arrancar la aplicación, el programa realiza las siguientes tareas automáticas y estructuradas:

1. **Apertura Instantánea (GUI):** La interfaz visual (construida sobre `Tkinter`) se abre de inmediato para que no tengas que esperar tiempos de carga.
2. **Actualización Silenciosa de la Base de Datos:** En segundo plano (vía *multithreading*), el programa se conecta a este repositorio de GitHub y descarga/actualiza el manifiesto original `id_y_ubicacion_saves.yaml` llevándoselo de forma invisible a tu carpeta local `%LOCALAPPDATA%`.
3. **Escaneo de Launchers Activos:** El script consulta las APIs, archivos de manifiesto (`.acf`, `.item`) y registros de Windows (`winreg`) para identificar qué juegos tienes **realmente instalados** en las siguientes plataformas:
   * **Steam** (Lee `libraryfolders.vdf` y los manifiestos de juego).
   * **Epic Games Store** (Lee los manifiestos de la ruta de instalación and de `ProgramData`).
   * **GOG.com / GOG Galaxy** (Navega por las claves del registro del sistema).
   * **Battle.net** (Detecta rutas de instalación de títulos de Blizzard).
   * **Ubisoft Connect** (Rastrea los directorios del launcher).
4. **Resolución Exacta de Rutas:** Para cada juego detectado, lee su ficha en el `.yaml` e interpreta las plantillas de rutas del sistema (como `<winAppData>`, `<winDocuments>`, o la ID única del jugador `<storeUserId>`), traduciéndolas a carpetas reales y físicas en tu disco duro.
5. **Función de "Intuición" Integrada:** Si un juego reciente no está en la base de datos o usa rutas variables, el motor utiliza un algoritmo de cruce de nombres (*alias*) buscando subcarpetas parecidas en directorios de editoras conocidas (como *Rockstar Games*), asegurando que casi ningún juego se quede atrás.

---

## ✨ Características Destacadas

* **Instalación Cero:** El programa es portable y centraliza todos sus registros en un directorio aislado en la ruta de usuario, previniendo pérdidas accidentales si borras la carpeta de descargas.
* **Filtro de Juegos Online:** El software detecta y omite automáticamente herramientas de sistema (como runtimes de Proton, benchmarks) y juegos 100% online cuyo progreso vive en servidores externos y no tienen partida local que perder (ej. *DayZ*, *Rust*, *Counter-Strike 2*, *Killing Floor 2*, *Apex Legends*).
* **Soporte para Juegos sin Launcher:** Incluye una sección especial para añadir carpetas raíces de juegos portables, emuladores o títulos DRM-Free. Cada subcarpeta que dejes ahí se tratará como un juego independiente y se cruzará con la base de datos global.
* **Gestión de Respaldos Seguros:** Copia tus archivos de manera rápida y nativa usando comandos optimizados del sistema (`robocopy`). Además, cuenta con un sistema de rotación que mueve copias antiguas a carpetas `old/` para evitar que un guardado corrupto machaque tu copia de seguridad buena.
* **Sistema de Diagnóstico Avanzado:** Cuenta con una herramienta interactiva donde puedes escribir el nombre de cualquier juego para comprobar su estado de instalación, qué launcher lo reporta y qué rutas exactas está intentando resolver el manifiesto.

---

## 🛠️ Para Desarrolladores y Contribuciones

Si quieres ejecutar el script desde el entorno de desarrollo o quieres ayudar a expandir la base de datos:

### Requisitos
* Python 3.10 o superior (Desarrollado y testeado en **Python 3.13**).
* Dependencias: El script incluye un autoinstalador para `pyyaml` a través de subprocesos si no se detecta en el entorno de ejecución.

### Contribuir al manifiesto (.yaml)
El motor de este proyecto se alimenta del archivo `id_y_ubicacion_saves.yaml`. Si quieres añadir compatibilidad para un nuevo juego o corregir una ruta, solo debes enviar un *Pull Request* modificando el archivo YAML principal siguiendo la estructura del proyecto:

```yaml
- name: 'Nombre Exacto del Juego'
  ids:
    steam: 123456         # ID de la tienda (Opcional)
    gog: 987654321        # ID de GOG (Opcional)
  save_locations:
  - <winLocalAppData>/CarpetaDelJuego [os=windows]
  - <root>/userdata/<storeUserId>/123456/remote [os=windows, store=steam]
```

### Reporte de fallos
Si experimentas algún error o notas que la ruta de un juego instalado no se resuelve de forma correcta, utiliza la función interna de **Diagnóstico** del programa, copia el log resultante y abre un **Issue** en este repositorio para que podamos revisarlo.

---

## 📝 Créditos y Licencia
* **Desarrollo:** Proyecto creado y desarrollado por **nox.bat** (@_noxbat en X) con ayuda de IA.
