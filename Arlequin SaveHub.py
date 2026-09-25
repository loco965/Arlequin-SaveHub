# -*- coding: utf-8 -*-
"""
Gestor de partidas guardadas by nox.bat

Cambio principal respecto a la versión anterior:
  - Ya NO se escanean carpetas a ciegas ni se cruzan nombres con carpetas
    "habituales" (Documents, My Games, Saved Games, AppData...).
  - Se consultan las APIs/registros de Steam, Epic, GOG, Battle.net y
    Ubisoft para saber qué juegos están INSTALADOS (y dónde).
  - Para cada juego instalado se consulta la base de datos propia del
    proyecto (id y ubicacion saves.yaml, repositorio Arlequin-SaveHub)
    para saber EXACTAMENTE dónde guarda sus partidas cada plataforma, y esa
    ruta se resuelve a una carpeta real del equipo.
  - Al arrancar, la app se abre primero (ventana visible) y SOLO DESPUÉS,
    en segundo plano, se descarga/actualiza la base de datos de Ludusavi.
"""

import os
import re
import json
import time
import shutil
import threading
import webbrowser
import urllib.request
import tkinter as tk
from tkinter import messagebox as mb
from tkinter import filedialog as fd
from tkinter import simpledialog as sd

try:
    import winreg
    _ES_WINDOWS = True
except ImportError:
    _ES_WINDOWS = False  # por si se abre el archivo fuera de Windows

try:
    import yaml
except ImportError:
    try:
        import subprocess
        import sys
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyyaml", "--quiet"])
        import yaml
    except Exception:
        yaml = None  # si no se puede instalar, el manifest no se podrá leer


DESKTOP_PATH = os.path.join(os.environ.get('USERPROFILE', ''), 'Desktop').replace("\\", "/")
if not os.path.exists(DESKTOP_PATH):
    DESKTOP_PATH = os.path.expanduser("~/Desktop").replace("\\", "/")

APP_GAMESAVES_DIR = os.path.join(os.getenv('LOCALAPPDATA') or os.path.expanduser("~"), 'APP GameSaves').replace("\\", "/")
if not os.path.exists(APP_GAMESAVES_DIR):
    os.makedirs(APP_GAMESAVES_DIR, exist_ok=True)

BKP = os.path.join(DESKTOP_PATH, 'Backup Saves').replace("\\", "/")
if not os.path.exists(BKP):
    os.makedirs(BKP, exist_ok=True)
UP = os.environ.get('USERPROFILE', os.path.expanduser('~')).replace("\\", "/")
M_O = os.path.join(APP_GAMESAVES_DIR, "juegos_ocultos.txt").replace("\\", "/")
M_M = os.path.join(APP_GAMESAVES_DIR, "juegos_manuales.txt").replace("\\", "/")
M_C = os.path.join(APP_GAMESAVES_DIR, "carpetas_sin_launcher.txt").replace("\\", "/")

# ---------------------------------------------------------------------------
#  BASE DE DATOS DE RUTAS DE SAVES (base propia de Arlequin-SaveHub)
# ---------------------------------------------------------------------------
# Formato: una LISTA de fichas (no un diccionario como el manifest.yaml
# original de Ludusavi). Cada ficha tiene:
#   name: "Nombre del juego"
#   ids:
#     steam: 12345          (opcional)
#     steamExtra: [111,222] (opcional, IDs de Steam adicionales del mismo juego)
#     gog: 67890             (opcional)
#     gogExtra: [333]        (opcional)
#     lutris: slug           (opcional, no se usa aquí)
#     flatpak: id            (opcional, no se usa aquí)
#   save_locations:
#     - "<plantilla>/de/ruta [os=windows, store=steam]"
# Las condiciones entre corchetes al final de cada ruta son opcionales; si
# faltan, la ruta se considera válida siempre. Varios valores de la misma
# clave (p. ej. "os=windows, os=linux") son un OR; claves distintas dentro
# del mismo corchete son un AND.
MANIFEST_URL = ("https://raw.githubusercontent.com/loco965/Arlequin-SaveHub/refs/heads/main/id%20y%20ubicacion%20saves.yaml")
MANIFEST_CACHE = os.path.join(APP_GAMESAVES_DIR, "arlequin_savehub_saves.yaml").replace("\\", "/")
MANIFEST_MAX_AGE_SEG = 60 * 60 * 24 * 7  # refrescar la caché cada 7 días como máximo

# Cómo se llama cada launcher dentro del campo "store" del manifest de Ludusavi
LAUNCHER_A_STORE = {
    "Steam": "steam",
    "Epic": "epic",
    "GOG": "gog",
    "Ubisoft": "uplay",
    "Battle.net": None,  # Ludusavi no distingue "battlenet" como store propio
}

# Nombre "bonito" para mostrar en la interfaz (la clave interna sigue siendo
# "Carpeta" para toda la lógica de detección/cruce con el manifest).
NOMBRE_VISUAL_LAUNCHER = {"Carpeta": "Juego sin Launcher"}

# Herramientas/componentes de sistema que algunos launchers (sobre todo
# Steam) reportan como si fueran "juegos instalados", pero que no tienen
# partidas guardadas propias: runtimes de compatibilidad, benchmarks, etc.
# Se comparan contra el nombre ya normalizado (_norm), así que basta con que
# el texto aparezca como subcadena, sin acentos ni mayúsculas.
EXCLUSIONES_SISTEMA = [
    "steam linux runtime",
    "proton",
    "lossless scaling",
    "3dmark",
]


def _es_exclusion_sistema(nombre_norm):
    return any(patron in nombre_norm for patron in EXCLUSIONES_SISTEMA)


# Juegos 100% online cuyo progreso (inventario, rango, base, personaje...)
# vive en el servidor o en la cuenta online del jugador, no en una carpeta de
# este PC. Cada uno de estos nombres se ha verificado contra el manifest de
# Ludusavi: SÍ tienen ficha propia, pero TODAS sus rutas 'files' para Windows
# están etiquetadas solo como 'config' (ajustes/keybinds/vídeo), nunca como
# 'save' — es decir, Ludusavi ya sabe que no hay partida real que respaldar
# ahí, así que en vez de mostrarlos como "sin datos de guardado" (que puede
# confundir con un fallo de la app) se omiten directamente, igual que
# EXCLUSIONES_SISTEMA. Se comparan por nombre normalizado exacto (ver _norm).
#
# OJO: esto NO es lo mismo que la categoría "ℹ️ SIN DATOS DE GUARDADO
# CONOCIDOS" del escaneo, que se deja SIN tocar para los demás casos: esa
# categoría sirve precisamente para detectar huecos reales del manifest
# (juegos que sí guardan partida pero Ludusavi aún no lo tiene bien mapeado,
# p. ej. "Darkest Dungeon" en este mismo manifest no tiene ninguna ruta
# 'files' registrada pese a que el juego sí guarda localmente). Solo se
# añaden aquí títulos multijugador online conocidos donde no existe partida
# local que perder. Añadir más es tan sencillo como incluir aquí el nombre
# normalizado del juego, idealmente tras comprobar su ficha en el manifest.
JUEGOS_SIN_SAVE_LOCAL_CONOCIDOS = [
    "dayz",                              # progreso vive en el servidor
    "rust",                              # progreso vive en el servidor
    "counter strike",                    # shooter competitivo, sin partida
    "counter strike 2",                  # shooter competitivo, sin partida
    "counter strike global offensive",   # mismo caso, nombre "clásico" de CS2
    "killing floor 2",                   # progreso ligado a la cuenta/server
    "valorant",                          # shooter competitivo, sin partida
    "apex legends",                      # battle royale, progreso en cuenta
    "overwatch 2",                       # shooter competitivo, sin partida
    "escape from tarkov",                # progreso vive en el servidor
    "league of legends",                 # progreso en la cuenta de Riot
    "dota 2",                            # progreso en la cuenta de Steam
    "peak",                              # co-op online, sin partida real
    "the finals",                        # shooter competitivo, sin partida
]


def _es_online_sin_save_local(nombre_norm):
    return nombre_norm in JUEGOS_SIN_SAVE_LOCAL_CONOCIDOS


# ---------------------------------------------------------------------------
#  DETECCIÓN DE JUEGOS INSTALADOS VÍA LOS LAUNCHERS
# ---------------------------------------------------------------------------

def _norm(s):
    """Normaliza un nombre de juego para comparar (minúsculas, sin símbolos)."""
    s = (s or "").lower()
    # 1) apóstrofos/acentos: se ELIMINAN (Baldur's -> baldurs)
    for ch in "'’´`´":
        s = s.replace(ch, "")
    # 2) resto de símbolos: se convierten en espacio (Cyberpunk™: -> cyberpunk )
    for ch in "™®©\":;.,_-–—!?()[]{}&+~^|/\\":
        s = s.replace(ch, " ")
    return " ".join(s.split())


# ---------------------------------------------------------------------------
#  MANIFEST DE LUDUSAVI: descarga, índice y resolución de rutas de saves
# ---------------------------------------------------------------------------

def descargar_manifest(forzar=False):
    """Descarga (o reutiliza la caché en disco) la base de datos de rutas de
    saves de Arlequin-SaveHub y la normaliza a un diccionario
    {nombre_juego: ficha}, que es el formato con el que trabaja el resto de
    la app (self.manifest)."""
    try:
        necesita_descarga = forzar or not os.path.exists(MANIFEST_CACHE)
        if not necesita_descarga:
            edad = time.time() - os.path.getmtime(MANIFEST_CACHE)
            necesita_descarga = edad > MANIFEST_MAX_AGE_SEG
        if necesita_descarga:
            peticion = urllib.request.Request(MANIFEST_URL, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(peticion, timeout=60) as resp:
                datos = resp.read()
            with open(MANIFEST_CACHE, "wb") as f:
                f.write(datos)
    except Exception:
        pass  # si falla la descarga (sin internet, etc.) se usa la caché si existe

    if yaml is None or not os.path.exists(MANIFEST_CACHE):
        return {}
    try:
        with open(MANIFEST_CACHE, "r", encoding="utf-8") as f:
            datos_yaml = yaml.safe_load(f)
    except Exception:
        return {}

    if isinstance(datos_yaml, dict):
        # Por si en el futuro se publica como diccionario {nombre: ficha}
        # en vez de como lista.
        return datos_yaml or {}

    manifest = {}
    for ficha in datos_yaml or []:
        if not isinstance(ficha, dict):
            continue
        nombre_juego = ficha.get("name")
        if not nombre_juego:
            continue
        manifest[nombre_juego] = ficha
    return manifest


def construir_indices_manifest(manifest):
    """Crea diccionarios de búsqueda rápida: por nombre normalizado, por ID de
    Steam y por ID de GOG, para poder localizar la ficha de cada juego."""
    por_nombre, por_steam_id, por_gog_id = {}, {}, {}
    for nombre_juego, datos in manifest.items():
        if not isinstance(datos, dict):
            continue
        clave = _norm(nombre_juego)
        if clave and clave not in por_nombre:
            por_nombre[clave] = nombre_juego
        ids = datos.get("ids") or {}
        try:
            steam_id = ids.get("steam")
            if steam_id:
                por_steam_id.setdefault(str(steam_id), nombre_juego)
            for extra_id in ids.get("steamExtra") or []:
                por_steam_id.setdefault(str(extra_id), nombre_juego)
        except Exception:
            pass
        try:
            gog_id = ids.get("gog")
            if gog_id:
                por_gog_id.setdefault(str(gog_id), nombre_juego)
            for extra_id in ids.get("gogExtra") or []:
                por_gog_id.setdefault(str(extra_id), nombre_juego)
        except Exception:
            pass
    return por_nombre, por_steam_id, por_gog_id


def obtener_steam_path():
    """Ruta raíz de instalación de Steam (donde vive la carpeta userdata)."""
    if not _ES_WINDOWS:
        return None
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam")
        steam_path = winreg.QueryValueEx(key, "SteamPath")[0]
        winreg.CloseKey(key)
        return steam_path.replace("\\", "/")
    except Exception:
        return None


def obtener_steam_user_ids(steam_path):
    """IDs numéricos (carpetas) de cuentas de Steam usadas localmente en este PC."""
    ids = []
    if not steam_path:
        return ids
    userdata = os.path.join(steam_path, "userdata")
    if os.path.isdir(userdata):
        for nombre in os.listdir(userdata):
            if nombre.isdigit():
                ids.append(nombre)
    return ids


def entorno_windows_base():
    """Valores fijos de las carpetas estándar de Windows usadas como
    placeholders en las rutas del manifest de Ludusavi."""
    home = UP
    return {
        "home": home,
        "winAppData": (os.environ.get("APPDATA") or "").replace("\\", "/"),
        "winLocalAppData": (os.environ.get("LOCALAPPDATA") or "").replace("\\", "/"),
        "winDocuments": os.path.join(home, "Documents").replace("\\", "/"),
        "winPublic": (os.environ.get("PUBLIC") or "C:/Users/Public").replace("\\", "/"),
        "winProgramData": (os.environ.get("PROGRAMDATA") or "C:/ProgramData").replace("\\", "/"),
        "winDir": (os.environ.get("WINDIR") or "C:/Windows").replace("\\", "/"),
        "osUserName": os.environ.get("USERNAME") or "",
    }


def resolver_plantilla_ruta(plantilla, contexto):
    """Sustituye los placeholders (<base>, <home>, <winAppData>...) de una ruta
    del manifest de Ludusavi por rutas reales del equipo. Devuelve una lista,
    porque <storeUserId> puede generar varias rutas candidatas (una por cuenta)."""
    p = plantilla.replace("\\", "/")

    reemplazos_simples = {
        "<home>": contexto.get("home", ""),
        "<root>": contexto.get("root", ""),
        "<base>": contexto.get("base", ""),
        "<winAppData>": contexto.get("winAppData", ""),
        "<winLocalAppData>": contexto.get("winLocalAppData", ""),
        "<winDocuments>": contexto.get("winDocuments", ""),
        "<winPublic>": contexto.get("winPublic", ""),
        "<winProgramData>": contexto.get("winProgramData", ""),
        "<winDir>": contexto.get("winDir", ""),
        "<osUserName>": contexto.get("osUserName", ""),
    }
    for marcador, valor in reemplazos_simples.items():
        if valor and marcador in p:
            p = p.replace(marcador, valor)

    # placeholders de Linux/Mac que no pintan nada en un equipo Windows
    if "<xdgData>" in p or "<xdgConfig>" in p or "<xdgCache>" in p:
        return []

    candidatos = [p]
    if "<storeUserId>" in p:
        ids_posibles = contexto.get("storeUserIds") or []
        if ids_posibles:
            candidatos = [p.replace("<storeUserId>", uid) for uid in ids_posibles]
            # Respaldo extra: las cuentas de Steam detectadas en userdata/ son
            # TODAS las que se han iniciado sesión alguna vez en este PC, no
            # necesariamente la que usa este juego en concreto (cuentas
            # antiguas, varios perfiles...), así que el ID "correcto" puede no
            # estar entre los candidatos de arriba aunque el juego SÍ tenga ya
            # guardado real ahí. Añadimos también la carpeta contenedora sin
            # ID (comodín) como candidata: si ninguno de los IDs concretos
            # existe pero esa carpeta padre sí (porque alguna cuenta ya
            # guardó ahí), la detectamos igualmente en vez de darla por no
            # creada todavía.
            candidatos.append(p.replace("<storeUserId>", "*"))
        else:
            # No sabemos el ID de cuenta en esta tienda (Epic, GOG...): lo
            # tratamos como un comodín y nos quedamos con la carpeta padre
            # (p. ej. ".../Saves/<storeUserId>" -> ".../Saves"), igual que
            # se hace más abajo con los comodines "*"/"**".
            candidatos = [p.replace("<storeUserId>", "*")]

    # las rutas restantes deben estar totalmente resueltas (sin placeholders)
    candidatos = [c for c in candidatos if "<" not in c and ">" not in c]

    # recorta comodines (*, **, *.ext, {random}...) hasta la carpeta
    # contenedora más cercana
    resultado = []
    for c in candidatos:
        partes = c.split("/")
        corte = len(partes)
        for i, parte in enumerate(partes):
            if "*" in parte or "{" in parte:
                corte = i
                break
        recortado = "/".join(partes[:corte]).rstrip("/")
        if recortado and recortado not in resultado:
            resultado.append(recortado)
    return resultado


_RE_CONDICIONES_RUTA = re.compile(r'^(.*?)\s*\[([^\]]*)\]\s*$', re.S)


def _parsear_entrada_save_location(entrada):
    """Separa una entrada de 'save_locations' (formato propio de
    Arlequin-SaveHub) en la plantilla de ruta y sus condiciones os=/store=
    entre corchetes, p. ej.:
        '<winAppData>/Foo/Bar [os=windows, store=steam]'
    -> ('<winAppData>/Foo/Bar', {'os': {'windows'}, 'store': {'steam'}})
    Sin corchetes al final, devuelve la ruta tal cual y condiciones vacías
    (aplica siempre)."""
    entrada = " ".join((entrada or "").split())  # normaliza el plegado de líneas de YAML
    m = _RE_CONDICIONES_RUTA.match(entrada)
    if not m:
        return entrada.strip(), {}
    plantilla = m.group(1).strip()
    condiciones = {}
    for parte in m.group(2).split(","):
        parte = parte.strip()
        if "=" not in parte:
            continue
        clave, valor = parte.split("=", 1)
        condiciones.setdefault(clave.strip(), set()).add(valor.strip())
    return plantilla, condiciones


def condicion_aplica_en_windows(condiciones, store_actual):
    """Formato propio de Arlequin-SaveHub: un único bloque de condiciones
    entre corchetes al final de la ruta (os=..., store=...). Varios valores
    de la misma clave son un OR ('os=windows, os=linux' = Windows O Linux);
    claves distintas dentro del mismo corchete son un AND (debe cumplir el
    SO Y, si se especifica, la tienda). Sin corchetes, aplica siempre."""
    if not condiciones:
        return True
    oses = condiciones.get("os")
    if oses and "windows" not in oses:
        return False
    stores = condiciones.get("store")
    if stores and store_actual and store_actual not in stores:
        return False
    return True


def obtener_rutas_guardado(datos_juego, contexto, store_actual):
    """A partir de la ficha del juego en la base de datos de Arlequin-SaveHub,
    devuelve la lista de carpetas reales (ya resueltas) donde debería estar
    guardando la partida."""
    rutas = []
    entradas = (datos_juego or {}).get("save_locations") or []
    for entrada in entradas:
        plantilla, condiciones = _parsear_entrada_save_location(entrada)
        if not plantilla:
            continue
        if not condicion_aplica_en_windows(condiciones, store_actual):
            continue
        for ruta in resolver_plantilla_ruta(plantilla, contexto):
            if ruta not in rutas:
                rutas.append(ruta)
    return rutas


# ---------------------------------------------------------------------------
#  "INTUICIÓN" DE RUTAS PARA JUEGOS QUE EL MANIFEST NO CUBRE BIEN
# ---------------------------------------------------------------------------
# Algunas editoras usan siempre el mismo patrón de carpeta bajo Documentos
# (p. ej. Rockstar Games guarda TODOS sus juegos en "Documents/Rockstar
# Games/<Juego>", tanto en Steam como en Epic). Cuando el manifest de
# Ludusavi no tiene ficha para el juego, o la tiene pero no resuelve ninguna
# ruta real (por ejemplo, porque aún no existe la del reciente "GTA V
# Enhanced"), probamos a buscar una subcarpeta con un nombre parecido dentro
# de estas rutas "editora conocida" como último recurso, antes de darlo por
# no localizado. Añadir más editoras a esta lista es tan sencillo como
# incluir su nombre de carpeta tal cual aparece bajo Documentos.
CARPETAS_EDITORAS_CONOCIDAS = [
    "Rockstar Games",  # GTA V/IV, Red Dead Redemption 1/2, Max Payne 3, L.A. Noire, Bully...
]

# Los nombres de carpeta de guardado no siempre coinciden con el nombre del
# juego tal y como lo reporta Steam/Epic/etc. Rockstar es el caso típico:
# "Grand Theft Auto V" (o "... V Enhanced") en la tienda, pero la carpeta de
# saves real se llama simplemente "GTA V". Este diccionario cubre esos casos
# conocidos (clave y valor ya normalizados con _norm).
ALIAS_CARPETA_JUEGO = {
    "grand theft auto v": "gta v",
    "grand theft auto v enhanced": "gta v",
    "grand theft auto v legacy": "gta v",
    "grand theft auto v premium edition": "gta v",
    "grand theft auto iv": "gta iv",
    "grand theft auto iv complete edition": "gta iv",
    "grand theft auto iv the complete edition": "gta iv",
    "grand theft auto san andreas": "gta san andreas",
    "grand theft auto vice city": "gta vice city",
    "grand theft auto iii": "gta iii",
}


def intuir_rutas_por_editoras_conocidas(nombre_juego, entorno):
    """Último recurso cuando el manifest no localiza nada: recorre las
    carpetas de editoras conocidas (ver CARPETAS_EDITORAS_CONOCIDAS) dentro
    de Documentos y devuelve las subcarpetas cuyo nombre se parece al del
    juego detectado (cruce por nombre normalizado, con soporte para los
    alias conocidos de ALIAS_CARPETA_JUEGO cuando el nombre de la carpeta no
    se parece nada al nombre "oficial" del juego)."""
    candidatas = []
    n_juego = _norm(nombre_juego)
    if not n_juego:
        return candidatas
    n_juego_alias = ALIAS_CARPETA_JUEGO.get(n_juego)
    documentos = entorno.get("winDocuments", "")
    if not documentos:
        return candidatas
    for editora in CARPETAS_EDITORAS_CONOCIDAS:
        raiz_editora = os.path.join(documentos, editora).replace("\\", "/")
        if not os.path.isdir(raiz_editora):
            continue
        try:
            for sub in os.listdir(raiz_editora):
                ruta_sub = os.path.join(raiz_editora, sub).replace("\\", "/")
                if not os.path.isdir(ruta_sub):
                    continue
                n_sub = _norm(sub)
                if not n_sub or len(n_sub) < 3:
                    continue
                coincide = n_sub in n_juego or n_juego in n_sub or (
                    n_juego_alias and (n_sub == n_juego_alias or n_juego_alias in n_sub or n_sub in n_juego_alias))
                if coincide:
                    candidatas.append(ruta_sub)
        except Exception:
            continue
    return candidatas


def detectar_juegos_steam():
    """Lee libraryfolders.vdf y los appmanifest_*.acf de cada librería."""
    juegos = []
    if not _ES_WINDOWS:
        return juegos
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam")
        steam_path = winreg.QueryValueEx(key, "SteamPath")[0]
        winreg.CloseKey(key)
    except Exception:
        return juegos

    librerias = [os.path.join(steam_path, "steamapps")]
    lf = os.path.join(steam_path, "steamapps", "libraryfolders.vdf")
    if os.path.exists(lf):
        try:
            texto = open(lf, encoding="utf-8", errors="ignore").read()
            for m in re.finditer(r'"path"\s+"([^"]+)"', texto):
                librerias.append(os.path.join(m.group(1).replace("\\\\", "\\"), "steamapps"))
        except Exception:
            pass

    for lib in librerias:
        if not os.path.isdir(lib):
            continue
        for f in os.listdir(lib):
            if not (f.startswith("appmanifest_") and f.endswith(".acf")):
                continue
            try:
                t = open(os.path.join(lib, f), encoding="utf-8", errors="ignore").read()
                m_name = re.search(r'"name"\s+"([^"]+)"', t)
                m_dir = re.search(r'"installdir"\s+"([^"]+)"', t)
                m_id = re.search(r'appmanifest_(\d+)\.acf$', f)
                if m_name:
                    juegos.append({
                        "nombre": m_name.group(1),
                        "launcher": "Steam",
                        "installdir": os.path.join(lib, "common", m_dir.group(1)) if m_dir else "",
                        "id": m_id.group(1) if m_id else None,
                    })
            except Exception:
                continue
    return juegos


def detectar_juegos_epic():
    """Lee los manifiestos .item que Epic Games Launcher deja en %ProgramData%.
    La ruta estándar (ProgramData\\Epic\\EpicGamesLauncher\\Data\\Manifests) se
    usa como método principal, porque en muchos equipos la clave de registro
    con 'AppDataPath' no existe o no se ha escrito; el registro queda como
    alternativa por si la instalación de Epic no está en la ruta estándar."""
    juegos = []
    if not _ES_WINDOWS:
        return juegos

    carpetas_manifiestos = []

    programdata = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
    ruta_estandar = os.path.join(programdata, "Epic", "EpicGamesLauncher", "Data", "Manifests")
    if os.path.isdir(ruta_estandar):
        carpetas_manifiestos.append(ruta_estandar)

    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                             r"SOFTWARE\WOW6432Node\Epic Games\EpicGamesLauncher")
        appdata = winreg.QueryValueEx(key, "AppDataPath")[0]
        winreg.CloseKey(key)
        ruta_registro = os.path.join(appdata, "Manifests")
        if os.path.isdir(ruta_registro) and ruta_registro not in carpetas_manifiestos:
            carpetas_manifiestos.append(ruta_registro)
    except Exception:
        pass

    if not carpetas_manifiestos:
        return juegos

    vistos = set()
    for manifiestos in carpetas_manifiestos:
        for f in os.listdir(manifiestos):
            if not f.endswith(".item"):
                continue
            try:
                datos = json.load(open(os.path.join(manifiestos, f), encoding="utf-8"))
                nombre = datos.get("DisplayName", "")
                installdir = datos.get("InstallLocation", "")
                if nombre and "launcher" not in _norm(nombre) and installdir and os.path.exists(installdir):
                    clave = _norm(nombre)
                    if clave in vistos:
                        continue
                    vistos.add(clave)
                    juegos.append({"nombre": nombre, "launcher": "Epic", "installdir": installdir, "id": None})
            except Exception:
                continue
    return juegos


def detectar_juegos_gog():
    """Lee HKLM\\SOFTWARE\\WOW6432Node\\GOG.com\\Games\\<id>."""
    juegos = []
    if not _ES_WINDOWS:
        return juegos
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\GOG.com\Games")
    except Exception:
        return juegos
    i = 0
    while True:
        try:
            sub = winreg.EnumKey(key, i)
            i += 1
        except OSError:
            break
        try:
            k2 = winreg.OpenKey(key, sub)
            nombre = winreg.QueryValueEx(k2, "gameName")[0]
            path = winreg.QueryValueEx(k2, "path")[0]
            winreg.CloseKey(k2)
            if nombre and os.path.exists(path):
                juegos.append({"nombre": nombre, "launcher": "GOG", "installdir": path, "id": sub})
        except Exception:
            continue
    try:
        winreg.CloseKey(key)
    except Exception:
        pass
    return juegos


NOMBRES_BNET = {
    "agent": None, "battle.net": None, "battle.net.exe": None,
    "destiny2": "Destiny 2",
    "diablo iii": "Diablo III", "diablo iv": "Diablo IV",
    "hearthstone": "Hearthstone",
    "heroes of the storm": "Heroes of the Storm",
    "overwatch": "Overwatch",
    "starcraft": "StarCraft", "starcraft ii": "StarCraft II",
    "warcraft iii": "Warcraft III",
    "world of warcraft": "World of Warcraft",
    "wow classic": "WoW Classic",
    "call of duty": "Call of Duty",
    "black ops cold war": "CoD: Black Ops Cold War",
    "black ops 6": "CoD: Black Ops 6",
    "modern warfare": "CoD: Modern Warfare",
    "modern warfare 2": "CoD: Modern Warfare II",
    "vanguard": "CoD: Vanguard", "warzone": "CoD: Warzone",
}


def detectar_juegos_battlenet():
    """Lee HKLM\\SOFTWARE\\WOW6432Node\\Blizzard Entertainment\\Battle.net\\Install."""
    juegos = []
    if not _ES_WINDOWS:
        return juegos
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                             r"SOFTWARE\WOW6432Node\Blizzard Entertainment\Battle.net\Install")
    except Exception:
        return juegos
    i = 0
    while True:
        try:
            sub = winreg.EnumKey(key, i)
            i += 1
        except OSError:
            break
        nombre = NOMBRES_BNET.get(sub.lower(), sub)
        if nombre is None:
            continue
        try:
            k2 = winreg.OpenKey(key, sub)
            path = winreg.QueryValueEx(k2, "InstallPath")[0]
            winreg.CloseKey(k2)
        except Exception:
            path = ""
        juegos.append({"nombre": nombre, "launcher": "Battle.net", "installdir": path, "id": None})
    try:
        winreg.CloseKey(key)
    except Exception:
        pass
    return juegos


def detectar_juegos_ubisoft():
    """Lee HKLM\\SOFTWARE\\WOW6432Node\\Ubisoft\\Launcher\\Installs."""
    juegos = []
    if not _ES_WINDOWS:
        return juegos
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                             r"SOFTWARE\WOW6432Node\Ubisoft\Launcher\Installs")
    except Exception:
        return juegos
    i = 0
    while True:
        try:
            sub = winreg.EnumKey(key, i)
            i += 1
        except OSError:
            break
        try:
            k2 = winreg.OpenKey(key, sub)
            path = winreg.QueryValueEx(k2, "InstallDir")[0]
            winreg.CloseKey(k2)
            nombre = os.path.basename(path.rstrip("\\/")) or f"Ubisoft #{sub}"
            juegos.append({"nombre": nombre, "launcher": "Ubisoft", "installdir": path, "id": None})
        except Exception:
            continue
    try:
        winreg.CloseKey(key)
    except Exception:
        pass
    return juegos


def detectar_todos_los_juegos():
    """Devuelve la lista completa de juegos instalados detectados vía launchers."""
    todos = []
    for fn in (detectar_juegos_steam, detectar_juegos_epic, detectar_juegos_gog,
               detectar_juegos_battlenet, detectar_juegos_ubisoft):
        try:
            todos.extend(fn())
        except Exception:
            continue
    return todos


def detectar_juegos_carpetas_raiz(carpetas_raiz):
    """Trata cada subcarpeta de las 'carpetas raíz sin launcher' indicadas por
    el usuario como un posible juego instalado. Pensado para juegos DRM-free
    (típico de GOG) o instalaciones portables que no dejan ningún registro,
    manifiesto ni ID en el equipo: la única pista es la carpeta donde viven.
    Se cruzan igual que el resto, por nombre normalizado, contra el manifest
    de Ludusavi (no tienen ID de tienda del que tirar)."""
    juegos = []
    for carpeta_raiz in (carpetas_raiz or []):
        if not carpeta_raiz or not os.path.isdir(carpeta_raiz):
            continue
        try:
            for nombre_sub in os.listdir(carpeta_raiz):
                ruta_sub = os.path.join(carpeta_raiz, nombre_sub).replace("\\", "/")
                if not os.path.isdir(ruta_sub):
                    continue
                juegos.append({
                    "nombre": nombre_sub,
                    "launcher": "Carpeta",
                    "installdir": ruta_sub,
                    "id": None,
                })
        except Exception:
            continue
    return juegos


# ---------------------------------------------------------------------------
#  APLICACIÓN
# ---------------------------------------------------------------------------

class GestorPartidasLocal:
    def abrir_carpeta_backups(self):
        if not os.path.exists(self.dest):
            os.makedirs(self.dest, exist_ok=True)
        os.startfile(os.path.normpath(self.dest))

    def cambiar_carpeta(self):
        r = fd.askdirectory(initialdir=self.dest)
        if r:
            self.dest = r
            self.lbl_r.config(text=f"Guardando en: {self.dest}")

    def centrar_ventana(self, ventana, ancho, alto):
        pantalla_ancho = ventana.winfo_screenwidth()
        pantalla_alto = ventana.winfo_screenheight()
        x = (pantalla_ancho // 2) - (ancho // 2)
        y = (pantalla_alto // 2) - (alto // 2)
        ventana.geometry(f"{ancho}x{alto}+{x}+{y}")

    def ejecutar_en_hilo(self, funcion):
        hilo = threading.Thread(target=funcion, daemon=True)
        hilo.start()

    def abrir_link_donar(self):
        webbrowser.open("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    def abrir_link_contacto(self):
        webbrowser.open("https://x.com/_noxbat")

    def seleccionar_todo_el_listado(self):
        self.box.selection_clear(0, tk.END)
        for i in range(self.box.size()):
            texto = self.box.get(i)
            if not texto.startswith("---") and texto != "":
                self.box.selection_set(i)

    def deseleccionar_todo_el_listado(self):
        self.box.selection_clear(0, tk.END)

    def get_sel_list(self):
        try:
            selección = self.box.curselection()
            if selección:
                elementos_validos = []
                for idx in selección:
                    texto_item = self.box.get(idx)
                    if not texto_item.startswith("---") and texto_item != "":
                        elementos_validos.append(texto_item)
                return elementos_validos
        except Exception:
            pass
        return []

    def limpiar_nombre_juego(self, texto_fila):
        res = texto_fila.replace("[👍 Copia Ok] ", "")
        res = res.replace("[Solo en Backup] ", "")
        res = res.strip()
        if " (" in res:
            partes = res.split(" (")
            res = " (".join(partes[:-1])
        return res.strip()

    def r_path(self, orig, nombre_juego_limpio):
        so = orig if os.path.isabs(orig) else os.path.join(UP, orig).replace("\\", "/")
        ultimo_directorio = os.path.basename(so)
        if ultimo_directorio.lower() == nombre_juego_limpio.lower():
            sub = nombre_juego_limpio
        else:
            sub = os.path.join(nombre_juego_limpio, ultimo_directorio)
        return os.path.join(self.dest, sub).replace("\\", "/"), so

    def check_bkp(self, folder):
        return folder.lower().strip() in self.backups_existentes

    def run_cmd(self, o, d):
        if os.path.isdir(o):
            os.makedirs(d, exist_ok=True)
            os.system(f'robocopy "{o}" "{d}" /E /R:1 /W:1 /NFL /NDL /NJH /NJS')
        elif os.path.isfile(o):
            os.makedirs(os.path.dirname(d), exist_ok=True)
            dir_o, file_o = os.path.split(o)
            dir_d = d if os.path.isdir(d) else os.path.dirname(d)
            os.system(f'robocopy "{dir_o}" "{dir_d}" "{file_o}" /R:1 /W:1 /NFL /NDL /NJH /NJS')

    def rotar_a_old(self, dst_actual):
        if os.path.exists(dst_actual):
            rel = os.path.relpath(dst_actual, self.dest)
            contador = 1
            while True:
                nombre_old = "old" if contador == 1 else f"old{contador}"
                camino_old = os.path.join(self.dest, nombre_old, rel).replace("\\", "/")
                if not os.path.exists(camino_old):
                    break
                contador += 1
            os.makedirs(os.path.dirname(camino_old), exist_ok=True)
            try:
                shutil.move(dst_actual, camino_old)
            except Exception:
                pass

    def rotar_original_en_pc(self, ruta_original_pc):
        if os.path.exists(ruta_original_pc):
            contador = 1
            while True:
                sufijo = "_old" if contador == 1 else f"_old{contador}"
                nueva_ruta_old = ruta_original_pc.rstrip("/") + sufijo
                if not os.path.exists(nueva_ruta_old):
                    break
                contador += 1
            try:
                shutil.move(ruta_original_pc, nueva_ruta_old)
            except Exception:
                pass

    def mostrar_submenu_ocultos(self):
        if not self.ocultos:
            mb.showinfo("Ocultos", "No tienes ningún elemento en la lista de ocultos actualmente.")
            return
        ventana_ocultos = tk.Toplevel(self.root)
        ventana_ocultos.title("Elementos Ocultados")
        ventana_ocultos.geometry("380x450")
        self.centrar_ventana(ventana_ocultos, 380, 450)
        ventana_ocultos.configure(bg="#2c3e50")
        ventana_ocultos.grab_set()
        tk.Label(ventana_ocultos, text="Lista de Elementos Ocultados", font=("Arial", 12, "bold"),
                 fg="#1abc9c", bg="#2c3e50").pack(pady=10)
        box_ocultos = tk.Listbox(ventana_ocultos, font=("Arial", 11), bg="#34495e", fg="white",
                                 selectbackground="#1abc9c", bd=0, highlightthickness=0,
                                 selectmode="multiple")
        box_ocultos.pack(padx=15, pady=5, fill="both", expand=True)
        for item in sorted(list(self.ocultos)):
            box_ocultos.insert(tk.END, item)

        def restaurar_elementos_multiples():
            selección = box_ocultos.curselection()
            if not selección:
                mb.showwarning("Atención", "Selecciona uno o varios elementos de la lista para restaurarlos.",
                               parent=ventana_ocultos)
                return
            elementos_a_quitar = [box_ocultos.get(idx) for idx in selección]
            if mb.askyesno("Restaurar", f"¿Quieres volver a mostrar los {len(elementos_a_quitar)} elementos seleccionados en el escáner principal?",
                           parent=ventana_ocultos):
                for nombre_item in elementos_a_quitar:
                    if nombre_item in self.ocultos:
                        self.ocultos.remove(nombre_item)
                self.save_data(M_O, self.ocultos)
                box_ocultos.delete(0, tk.END)
                for item in sorted(list(self.ocultos)):
                    box_ocultos.insert(tk.END, item)
                self.scan()
                if not self.ocultos:
                    ventana_ocultos.destroy()

        tk.Button(ventana_ocultos, text="✅ Volver a mostrar seleccionado(s)",
                  command=restaurar_elementos_multiples, bg="#2ecc71", fg="white",
                  font=("Arial", 10, "bold"), bd=0, pady=8, cursor="hand2").pack(fill="x", padx=15, pady=15)

    def hide(self):
        lista_seleccionados = self.get_sel_list()
        if lista_seleccionados:
            if mb.askyesno("Ocultar", f"¿Quieres ocultar los {len(lista_seleccionados)} elementos seleccionados de la vista?"):
                for tag_juego in lista_seleccionados:
                    nombre_limpio = self.limpiar_nombre_juego(tag_juego)
                    self.ocultos.add(nombre_limpio)
                self.save_data(M_O, self.ocultos)
                self.scan()

    def añadir_carpeta_manual(self):
        ruta_seleccionada = fd.askdirectory(title="Selecciona la carpeta donde están las partidas guardadas")
        if not ruta_seleccionada:
            return
        nombre_juego = sd.askstring("Nombre del Juego", "¿Qué nombre quieres darle a este juego en la lista?")
        if not nombre_juego or not nombre_juego.strip():
            mb.showwarning("Atención", "Debes asignar un nombre válido para identificar la carpeta.")
            return
        nombre_juego = nombre_juego.strip()
        self.manuales[nombre_juego] = ruta_seleccionada.replace("\\", "/")
        lineas_a_guardar = [f"{k}|||{v}" for k, v in self.manuales.items()]
        self.save_data(M_M, lineas_a_guardar)
        mb.showinfo("Éxito", f"¡Se ha añadido '{nombre_juego}' correctamente! El sistema volverá a escanear.")
        self.scan()

    def quitar_carpeta_manual(self):
        lista_seleccionados = self.get_sel_list()
        if not lista_seleccionados:
            mb.showwarning("Atención", "Por favor, selecciona uno o varios elementos manuales de la lista para quitarlos.")
            return
        manuales_a_eliminar = []
        for tag_seleccionado in lista_seleccionados:
            nombre_limpio = self.limpiar_nombre_juego(tag_seleccionado)
            if nombre_limpio in self.manuales:
                manuales_a_eliminar.append(nombre_limpio)
        if not manuales_a_eliminar:
            mb.showwarning("Atención", "Ninguno de los elementos seleccionados pertenece a la lista de carpetas manuales.")
            return
        if mb.askyesno("Quitar Manual", f"¿Quieres quitar los {len(manuales_a_eliminar)} juegos manuales seleccionados de la lista?\n(Esto NO borrará tus partidas guardadas del disco)."):
            for juego in manuales_a_eliminar:
                if juego in self.manuales:
                    del self.manuales[juego]
            lineas_a_guardar = [f"{k}|||{v}" for k, v in self.manuales.items()]
            self.save_data(M_M, lineas_a_guardar)
            self.scan()

    def load_manuales(self, path):
        if not os.path.exists(path):
            return {}
        dict_manuales = {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                for linea in f:
                    if "|||" in linea:
                        partes = linea.strip().split("|||")
                        if len(partes) == 2:
                            dict_manuales[partes[0]] = partes[1]
            return dict_manuales
        except Exception:
            return {}

    def load_carpetas(self, path):
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                return [linea.strip().replace("\\", "/") for linea in f if linea.strip()]
        except Exception:
            return []

    def gestionar_carpetas_sin_launcher(self):
        ventana = tk.Toplevel(self.root)
        ventana.title("Juegos sin Launcher (DRM-free / portables)")
        ventana.geometry("480x440")
        self.centrar_ventana(ventana, 480, 440)
        ventana.configure(bg="#2c3e50")
        ventana.grab_set()
        tk.Label(ventana, text="Juegos sin Launcher", font=("Arial", 12, "bold"),
                 fg="#1abc9c", bg="#2c3e50").pack(pady=10)
        tk.Label(ventana,
                 text="Cada subcarpeta directa dentro de estas rutas se tratará\n"
                      "como un posible juego (p. ej. instalaciones DRM-free de\n"
                      "GOG o ejecutables portables), cruzándose por nombre con\n"
                      "la base de datos de Arlequin-SaveHub igual que el resto.",
                 font=("Arial", 9), fg="#bdc3c7", bg="#2c3e50", justify="left").pack(pady=(0, 8), padx=15)
        box = tk.Listbox(ventana, font=("Arial", 10), bg="#34495e", fg="white",
                          selectbackground="#1abc9c", bd=0, highlightthickness=0,
                          selectmode="multiple")
        box.pack(padx=15, pady=5, fill="both", expand=True)
        for c in self.carpetas_sin_launcher:
            box.insert(tk.END, c)

        def añadir():
            r = fd.askdirectory(title="Selecciona la carpeta raíz de tus juegos sin launcher")
            if r:
                r = r.replace("\\", "/")
                if r not in self.carpetas_sin_launcher:
                    self.carpetas_sin_launcher.append(r)
                    box.insert(tk.END, r)
                    self.save_data(M_C, self.carpetas_sin_launcher)

        def quitar():
            seleccion = box.curselection()
            if not seleccion:
                mb.showwarning("Atención", "Selecciona una o varias carpetas para quitarlas.", parent=ventana)
                return
            elementos = [box.get(i) for i in seleccion]
            for e in elementos:
                if e in self.carpetas_sin_launcher:
                    self.carpetas_sin_launcher.remove(e)
            for i in reversed(seleccion):
                box.delete(i)
            self.save_data(M_C, self.carpetas_sin_launcher)

        f_btns = tk.Frame(ventana, bg="#2c3e50")
        f_btns.pack(fill="x", padx=15, pady=10)
        tk.Button(f_btns, text="➕ Añadir carpeta", command=añadir, bg="#2ecc71", fg="white",
                  font=("Arial", 9, "bold"), bd=0, pady=6, cursor="hand2").pack(side="left", fill="x", expand=True, padx=(0, 5))
        tk.Button(f_btns, text="➖ Quitar seleccionada(s)", command=quitar, bg="#e67e22", fg="white",
                  font=("Arial", 9, "bold"), bd=0, pady=6, cursor="hand2").pack(side="left", fill="x", expand=True, padx=(5, 0))

        def cerrar_y_reescanear():
            ventana.destroy()
            self.ejecutar_en_hilo(self.scan)

        tk.Button(ventana, text="✅ Cerrar y reescanear", command=cerrar_y_reescanear, bg="#3498db",
                  fg="white", font=("Arial", 10, "bold"), bd=0, pady=8, cursor="hand2").pack(fill="x", padx=15, pady=(0, 15))

    def _folder_size_bytes(self, path):
        """Devuelve el tamaño en bytes de 'path' (0 si no existe o falla)."""
        if not path or not os.path.exists(path):
            return 0
        total_size = 0
        try:
            if os.path.isdir(path):
                for dirpath, dirnames, filenames in os.walk(path):
                    for f in filenames:
                        fp = os.path.join(dirpath, f)
                        if os.path.exists(fp):
                            total_size += os.path.getsize(fp)
            else:
                total_size = os.path.getsize(path)
        except Exception:
            return 0
        return total_size

    def _formatear_bytes(self, total_size):
        for unit in ['B', 'KB', 'MB', 'GB']:
            if total_size < 1024.0:
                return f"{total_size:.2f} {unit}"
            total_size /= 1024.0
        return f"{total_size:.2f} TB"

    def get_folder_size_str(self, path):
        if not path or not os.path.exists(path):
            return "No Encontrada"
        try:
            return self._formatear_bytes(self._folder_size_bytes(path))
        except Exception:
            return "Error Tam."

    def get_rutas_size_str(self, rutas):
        """Tamaño combinado de una o varias carpetas de save del MISMO juego
        (se usa para fusionar duplicados en una sola línea de la lista)."""
        if not rutas:
            return "No Encontrada"
        if isinstance(rutas, str):
            return self.get_folder_size_str(rutas)
        total = sum(self._folder_size_bytes(r) for r in rutas)
        return self._formatear_bytes(total)

    def op(self, mode):
        lista_seleccionados = self.get_sel_list()
        if not lista_seleccionados:
            mb.showwarning("Atención", "Por favor, selecciona uno o varios elementos de la lista haciendo clic sobre ellos.")
            return
        c = 0
        for tag_seleccionado in lista_seleccionados:
            if tag_seleccionado in self.juegos:
                origen = self.juegos[tag_seleccionado]
                if not origen:  # juego instalado sin carpeta de saves localizada
                    continue
                # Un mismo juego puede tener varias carpetas de save reales
                # (duplicados fusionados en una sola línea de la lista). Se
                # respaldan/restauran TODAS, pero cuentan como 1 sola partida.
                origenes = [origen] if isinstance(origen, str) else list(origen)
                nombre_limpio = self.limpiar_nombre_juego(tag_seleccionado)
                se_hizo_algo = False
                for orig in origenes:
                    dst, _ = self.r_path(orig, nombre_limpio)
                    if mode == 1:
                        if os.path.exists(orig):
                            self.rotar_a_old(dst)
                            self.run_cmd(orig, dst)
                            se_hizo_algo = True
                    elif mode == 2:
                        if os.path.exists(dst):
                            self.rotar_original_en_pc(orig)
                            self.run_cmd(dst, orig)
                            se_hizo_algo = True
                if se_hizo_algo:
                    c += 1

        def finalizar_operacion():
            accion_str = "respaldaron" if mode == 1 else "restauraron"
            mb.showinfo("Éxito", f"¡Operación completada! Se {accion_str} {c} partidas marcadas.")
            self.scan()

        self.root.after(0, finalizar_operacion)

    def indexar_backups_en_disco(self):
        self.backups_existentes.clear()
        if os.path.exists(self.dest) and os.path.isdir(self.dest):
            try:
                for elemento in os.listdir(self.dest):
                    if os.path.isdir(os.path.join(self.dest, elemento)) and elemento.lower().strip() not in ["old", "old2", "old3"]:
                        self.backups_existentes.add(elemento.lower().strip())
            except Exception:
                pass

    def load_ocultos(self, path):
        if not os.path.exists(path):
            return set()
        try:
            with open(path, "r", encoding="utf-8") as f:
                return set([linea.strip() for linea in f if linea.strip()])
        except Exception:
            return set()

    def save_data(self, path, data):
        try:
            with open(path, "w", encoding="utf-8") as f:
                for item in sorted(list(data)):
                    f.write(f"{item}\n")
        except Exception:
            pass

    # -- NUEVO: base de datos Arlequin-SaveHub + detección vía launchers ---

    def actualizar_base_de_datos(self, forzar=False):
        """Descarga/lee la base de datos de Arlequin-SaveHub y construye los índices de
        búsqueda. Se llama SIEMPRE en segundo plano, después de que la
        ventana ya esté abierta."""
        def avisar(texto, color):
            self.root.after(0, lambda: self.lbl_db_status.config(text=texto, fg=color))

        avisar("⏳ Actualizando base de datos de saves (Arlequin-SaveHub)...", "#f1c40f")
        self.manifest = descargar_manifest(forzar=forzar)
        self.manifest_por_nombre, self.manifest_por_steam_id, self.manifest_por_gog_id = \
            construir_indices_manifest(self.manifest)
        if self.manifest:
            avisar(f"✅ Base de datos actualizada ({len(self.manifest)} juegos conocidos)", "#2ecc71")
        else:
            avisar("⚠️ No se pudo descargar la base de datos (sin conexión). Reintenta más tarde.", "#e67e22")

    def actualizar_bd_y_escanear(self, forzar=False):
        self.actualizar_base_de_datos(forzar=forzar)
        self.scan()

    def buscar_en_manifest(self, info_juego):
        """Devuelve la clave (nombre exacto tal cual está en el manifest) del
        juego, intentando primero por ID de tienda (Steam/GOG, más fiable) y
        si no por coincidencia de nombre."""
        store = LAUNCHER_A_STORE.get(info_juego["launcher"])
        id_juego = info_juego.get("id")
        if store == "steam" and id_juego and id_juego in self.manifest_por_steam_id:
            return self.manifest_por_steam_id[id_juego]
        if store == "gog" and id_juego and id_juego in self.manifest_por_gog_id:
            return self.manifest_por_gog_id[id_juego]

        n = _norm(info_juego["nombre"])
        if not n:
            return None
        if n in self.manifest_por_nombre:
            return self.manifest_por_nombre[n]
        for k_norm, k_real in self.manifest_por_nombre.items():
            if len(k_norm) >= 4 and (k_norm in n or n in k_norm):
                return k_real
        return None

    # -- NUEVO: diagnóstico manual de un juego concreto ---------------------

    def diagnostico_juego(self):
        nombre_buscado = sd.askstring(
            "Diagnóstico",
            "¿Qué juego quieres diagnosticar? (escribe el nombre, aproximado vale)")
        if not nombre_buscado or not nombre_buscado.strip():
            return
        self.ejecutar_en_hilo(lambda: self._diagnostico_juego_hilo(nombre_buscado.strip()))

    def _diagnostico_juego_hilo(self, nombre_buscado):
        n_buscado = _norm(nombre_buscado)
        lineas = [f"🔍 Diagnóstico para: '{nombre_buscado}'", ""]

        instalados = detectar_todos_los_juegos() + detectar_juegos_carpetas_raiz(self.carpetas_sin_launcher)
        lineas.append(f"(Total de juegos detectados como instalados en el equipo: {len(instalados)})")
        lineas.append("")
        coincidencias = [j for j in instalados
                         if n_buscado and (n_buscado in _norm(j["nombre"]) or _norm(j["nombre"]) in n_buscado)]

        if not coincidencias:
            lineas.append("❌ Ningún launcher (Steam/Epic/GOG/Battle.net/Ubisoft) reporta ese juego como instalado.")
            lineas.append("   Posibles causas:")
            lineas.append("   • El registro de ese launcher no se ha podido leer en este PC.")
            lineas.append("   • El nombre que usa el launcher difiere mucho del que has escrito.")
        else:
            for info in coincidencias:
                lineas.append(f"✅ Detectado como INSTALADO: '{info['nombre']}'  (launcher: {info['launcher']}, id: {info.get('id')})")
                lineas.append(f"   installdir: {info.get('installdir') or '(vacío)'}")

                clave_norm_info = _norm(info["nombre"])
                if _es_exclusion_sistema(clave_norm_info):
                    lineas.append("   ⏭️ Excluido a propósito (EXCLUSIONES_SISTEMA): es un runtime/herramienta")
                    lineas.append("      de sistema, no un juego con partida guardada. No aparece en ningún")
                    lineas.append("      bloque del escaneo.")
                    lineas.append("")
                    continue
                if _es_online_sin_save_local(clave_norm_info):
                    lineas.append("   ⏭️ Excluido a propósito (JUEGOS_SIN_SAVE_LOCAL_CONOCIDOS): es un juego")
                    lineas.append("      100% online cuyo progreso vive en el servidor, no en este PC. Aunque")
                    lineas.append("      el manifest pueda resolver una carpeta local, ahí solo hay ajustes,")
                    lineas.append("      no partida real, así que se omite por completo del escaneo.")
                    lineas.append("")
                    continue

                if not self.manifest:
                    lineas.append("   ⚠️ La base de datos de Arlequin-SaveHub todavía no está cargada.")
                    lineas.append("      Espera a que termine de actualizar o pulsa '🔄 Actualizar BD'.")
                    lineas.append("")
                    continue

                clave_manifest = self.buscar_en_manifest(info)
                if not clave_manifest:
                    lineas.append("   ❌ No hay ninguna ficha en la base de datos que cruce con ese nombre.")
                    rutas_intuidas = intuir_rutas_por_editoras_conocidas(info["nombre"], entorno_windows_base())
                    if rutas_intuidas:
                        lineas.append("   🔎 Pero se ha intuido por carpeta de editora conocida (Rockstar Games, etc.):")
                        for r in rutas_intuidas:
                            lineas.append(f"      -> {r}   [✅ EXISTE en disco]")
                    else:
                        lineas.append("      Tampoco coincide con ninguna carpeta de editora conocida (Rockstar Games...).")
                    lineas.append("")
                    continue

                lineas.append(f"   📖 Ficha de la base de datos: '{clave_manifest}'")
                datos_juego = self.manifest.get(clave_manifest) or {}
                entradas = datos_juego.get("save_locations") or []
                entorno = entorno_windows_base()
                if not entradas:
                    lineas.append("   ⚠️ Esa ficha no tiene ninguna ruta en 'save_locations'.")
                    rutas_intuidas = intuir_rutas_por_editoras_conocidas(info["nombre"], entorno)
                    if rutas_intuidas:
                        lineas.append("   🔎 Pero se ha intuido por carpeta de editora conocida (Rockstar Games, etc.):")
                        for r in rutas_intuidas:
                            lineas.append(f"      -> {r}   [✅ EXISTE en disco]")
                    lineas.append("")
                    continue

                steam_path = obtener_steam_path()
                steam_user_ids = obtener_steam_user_ids(steam_path)
                store = LAUNCHER_A_STORE.get(info["launcher"])
                installdir = (info.get("installdir") or "").replace("\\", "/")
                contexto = dict(entorno)
                contexto["base"] = installdir
                contexto["root"] = steam_path if store == "steam" else (
                    os.path.dirname(installdir) if installdir else "")
                contexto["storeUserIds"] = steam_user_ids if store == "steam" else []

                alguna_ruta_existe = False
                rutas_resueltas_total = []
                for entrada in entradas:
                    plantilla, condiciones = _parsear_entrada_save_location(entrada)
                    cumple_cond = condicion_aplica_en_windows(condiciones, store)
                    se_usa = bool(plantilla) and cumple_cond
                    cond_str = ", ".join(
                        f"{k}={'/'.join(sorted(v))}" for k, v in condiciones.items()) or "(ninguna)"
                    lineas.append(f"   • Plantilla: {plantilla}")
                    lineas.append(f"     condiciones=[{cond_str}] | ¿aplica en Windows/tienda?={cumple_cond} "
                                  f"| {'✅ SE USA' if se_usa else '⏭️ descartada (OS/tienda distinta)'}")
                    if se_usa:
                        rutas = resolver_plantilla_ruta(plantilla, contexto)
                        if not rutas:
                            lineas.append("     -> no se pudo resolver a una ruta real (falta algún placeholder)")
                        rutas_resueltas_total.extend(rutas)
                        for r in rutas:
                            existe = os.path.isdir(r)
                            alguna_ruta_existe = alguna_ruta_existe or existe
                            lineas.append(f"     -> {r}   [{'✅ EXISTE en disco' if existe else '❌ no existe en disco'}]")

                if not alguna_ruta_existe:
                    rutas_intuidas = intuir_rutas_por_editoras_conocidas(info["nombre"], entorno)
                    if rutas_intuidas:
                        lineas.append("   🔎 Ninguna ruta del manifest existe, pero se ha intuido por carpeta")
                        lineas.append("      de editora conocida (Rockstar Games, etc.):")
                        for r in rutas_intuidas:
                            lineas.append(f"      -> {r}   [✅ EXISTE en disco]")
                    elif rutas_resueltas_total:
                        lineas.append("   📌 El manifest SÍ cruzó y SÍ sabe resolver la ruta, pero esa carpeta")
                        lineas.append("      todavía no existe en disco. Lo más probable es que el juego esté")
                        lineas.append("      instalado pero no se haya ejecutado ni una vez en este Windows")
                        lineas.append("      (muchos juegos no crean su carpeta de guardado hasta el primer")
                        lineas.append("      arranque). Aparecerá en el bloque '📌 RUTA PREVISTA' del escaneo,")
                        lineas.append("      y pasará solo a 'encontrados' en cuanto abras/juegues el título")
                        lineas.append("      una vez (no hace falta terminar una partida, basta con que el")
                        lineas.append("      juego cree su carpeta de perfil/guardado al arrancar).")
                    else:
                        lineas.append("   ℹ️ El manifest SÍ cruzó, pero ninguna de sus rutas está marcada como")
                        lineas.append("      'save' para Windows (solo config/registro, o ninguna se pudo")
                        lineas.append("      resolver). La base de datos no tiene datos de guardado registrados para")
                        lineas.append("      este juego — no es un fallo de detección: lo más probable es que")
                        lineas.append("      no tenga partida persistente que respaldar (típico en shooters")
                        lineas.append("      competitivos como Counter-Strike 2, o en juegos sin sistema de")
                        lineas.append("      guardado como tal, p. ej. PEAK). Aparecerá en el bloque")
                        lineas.append("      'ℹ️ SIN DATOS DE GUARDADO CONOCIDOS' del escaneo.")
                lineas.append("")

        texto_final = "\n".join(lineas)
        self.root.after(0, lambda: self._mostrar_diagnostico(texto_final))

    def _mostrar_diagnostico(self, texto):
        ventana = tk.Toplevel(self.root)
        ventana.title("Diagnóstico")
        ventana.geometry("680x520")
        self.centrar_ventana(ventana, 680, 520)
        ventana.configure(bg="#2c3e50")
        caja = tk.Text(ventana, bg="#1b2731", fg="#ecf0f1", font=("Consolas", 9), wrap="word", bd=0)
        caja.pack(fill="both", expand=True, padx=10, pady=10)
        caja.insert("1.0", texto)
        caja.config(state="disabled")

    def localizar_saves_instalados(self):
        """Para cada juego instalado (detectado vía Steam/Epic/GOG/Battle.net/
        Ubisoft/carpetas sin launcher), busca su ficha en el manifest de
        Ludusavi y resuelve la(s) carpeta(s) real(es) de guardado en este
        equipo.
        Devuelve (encontrados, previstos, sin_datos, sin_localizar,
        conteo_launchers) donde:
          - encontrados: lista de (nombre, launcher, ruta_carpeta) cuya
            carpeta YA existe en disco.
          - previstos: lista de (nombre, launcher, ruta_prevista) para
            juegos cuya ficha del manifest SÍ cruzó y SÍ se pudo resolver
            una ruta real, pero esa carpeta todavía no existe en disco —
            típicamente porque el juego está instalado pero no se ha
            ejecutado ni una vez en esta instalación/perfil de Windows
            (muchos juegos no crean su carpeta de guardado hasta el primer
            arranque). En cuanto lo abras/juegues una vez, el siguiente
            escaneo la moverá sola a "encontrados".
          - sin_datos: lista de (nombre, launcher) para juegos cuya ficha
            del manifest SÍ cruzó (Ludusavi conoce el juego), pero esa
            ficha no tiene ninguna ruta marcada como 'save' para Windows
            (solo config, solo registro, o directamente sin sección
            'files'). No es un fallo de detección: significa que Ludusavi
            no tiene constancia de que ese juego guarde partida en disco
            — típico de shooters competitivos sin progreso persistente
            (p. ej. Counter-Strike 2) o de juegos sin sistema de guardado
            como tal (p. ej. PEAK, que solo guarda ajustes, no partidas).
          - sin_localizar: lista de (nombre, launcher) que están instalados
            pero de los que no se pudo ni cruzar con el manifest ni resolver
            ninguna ruta candidata (nombre no reconocido por Ludusavi, etc.)
        Cuando el mismo juego se detecta por dos vías a la vez (p. ej. ya lo
        tienes en Steam y además en una carpeta sin launcher), se queda con
        la que dé mejor resultado (rutas reales > ruta prevista > cruce sin
        datos > nada), en vez de quedarse ciegamente con la primera que se
        procesó y descartar la otra en silencio.
        """
        entorno = entorno_windows_base()
        steam_path = obtener_steam_path()
        steam_user_ids = obtener_steam_user_ids(steam_path)

        conteo_launchers = {}
        mejores_por_nombre = {}  # clave_norm -> {"nombre", "launcher", "rutas", "previstas", "sin_datos"}

        def rango(d):
            if d["rutas"]:
                return 3
            if d["previstas"]:
                return 2
            if d.get("sin_datos"):
                return 1
            return 0

        todos_los_detectados = detectar_todos_los_juegos() + detectar_juegos_carpetas_raiz(self.carpetas_sin_launcher)
        for info in todos_los_detectados:
            clave_norm = _norm(info["nombre"])
            if not clave_norm:
                continue
            # Runtimes/herramientas de sistema (Steam Linux Runtime, Proton,
            # Lossless Scaling, 3DMark...): no son juegos con partida
            # guardada, así que ni se cuentan ni aparecen en ningún bloque.
            if _es_exclusion_sistema(clave_norm):
                continue
            if _es_online_sin_save_local(clave_norm):
                continue
            conteo_launchers[info["launcher"]] = conteo_launchers.get(info["launcher"], 0) + 1
            if info["nombre"] in self.ocultos:
                continue

            # Si ya tenemos una entrada para este mismo juego (por otra vía)
            # y esa entrada YA localizó una carpeta de saves real, no hace
            # falta volver a resolver esta: nos quedamos con la que ya funciona.
            existente = mejores_por_nombre.get(clave_norm)
            if existente and existente["rutas"]:
                continue

            store = LAUNCHER_A_STORE.get(info["launcher"])
            clave_manifest = self.buscar_en_manifest(info) if self.manifest else None

            rutas_validas = []
            rutas_previstas = []
            sin_datos_guardado = False
            if clave_manifest:
                datos_juego = self.manifest.get(clave_manifest) or {}
                installdir = (info.get("installdir") or "").replace("\\", "/")
                contexto = dict(entorno)
                contexto["base"] = installdir
                contexto["root"] = steam_path if store == "steam" else (
                    os.path.dirname(installdir) if installdir else "")
                contexto["storeUserIds"] = steam_user_ids if store == "steam" else []

                rutas_resueltas = obtener_rutas_guardado(datos_juego, contexto, store)
                rutas_validas = [r for r in rutas_resueltas if os.path.isdir(r)]
                if not rutas_validas:
                    if rutas_resueltas:
                        # El manifest cruzó y sí sabe resolver la ruta, pero
                        # esa carpeta aún no existe en disco: lo más probable
                        # es que el juego esté instalado pero nunca se haya
                        # ejecutado en este Windows. La guardamos como
                        # "prevista" en vez de descartarla sin más.
                        rutas_previstas = rutas_resueltas
                    else:
                        # El juego SÍ está en el manifest, pero ninguna de
                        # sus rutas 'files' está etiquetada como 'save' para
                        # Windows (o la ficha no tiene 'files' en absoluto).
                        # No es un fallo: la base de datos no tiene datos de
                        # guardado registrados para este título.
                        sin_datos_guardado = True

            # Último recurso: si el manifest no tenía ficha, o la tenía pero
            # no resolvió ninguna ruta real, probamos con las carpetas de
            # editoras conocidas (Rockstar Games, etc. — ver
            # CARPETAS_EDITORAS_CONOCIDAS) por si el juego guarda ahí aunque
            # Ludusavi todavía no lo tenga bien mapeado.
            if not rutas_validas:
                intuidas = intuir_rutas_por_editoras_conocidas(info["nombre"], entorno)
                if intuidas:
                    rutas_validas = intuidas
                    rutas_previstas = []
                    sin_datos_guardado = False

            nuevo = {
                "nombre": info["nombre"], "launcher": info["launcher"],
                "rutas": rutas_validas, "previstas": rutas_previstas,
                "sin_datos": sin_datos_guardado,
            }
            if existente is None or rango(nuevo) > rango(existente):
                mejores_por_nombre[clave_norm] = nuevo

        encontrados = []
        previstos = []
        sin_datos = []
        sin_localizar = []
        for datos in mejores_por_nombre.values():
            if datos["rutas"]:
                for ruta in datos["rutas"]:
                    encontrados.append((datos["nombre"], datos["launcher"], ruta))
            elif datos["previstas"]:
                for ruta in datos["previstas"]:
                    previstos.append((datos["nombre"], datos["launcher"], ruta))
            elif datos["sin_datos"]:
                sin_datos.append((datos["nombre"], datos["launcher"]))
            else:
                sin_localizar.append((datos["nombre"], datos["launcher"]))

        return encontrados, previstos, sin_datos, sin_localizar, conteo_launchers

    def actualizar_label_launchers(self, conteo_launchers):
        if conteo_launchers:
            resumen = " · ".join(f"{NOMBRE_VISUAL_LAUNCHER.get(l, l)}: {c}"
                                 for l, c in sorted(conteo_launchers.items()))
            self.lbl_launchers_status.config(text=f"Juegos instalados detectados → {resumen}", fg="#2ecc71")
        else:
            self.lbl_launchers_status.config(text="No se detectó ningún launcher con juegos instalados", fg="#e67e22")

    # -- ESCANEO (ahora vía base de datos de Arlequin-SaveHub) --------------

    def scan(self):
        self.root.after(0, lambda: self.btn_scan.config(state="disabled", text="⏳ ESCANEANDO..."))
        self.juegos.clear()
        self.root.after(0, lambda: self.box.delete(0, tk.END))
        self.indexar_backups_en_disco()

        encontrados, previstos, sin_datos, sin_localizar, conteo_launchers = self.localizar_saves_instalados()
        self.root.after(0, lambda: self.actualizar_label_launchers(conteo_launchers))

        juegos_encontrados_global = set()
        total_items_detectados = 0

        elementos_a_insertar = []

        if self.manuales:
            elementos_a_insertar.append("")
            elementos_a_insertar.append("--- ➕ CARPETAS AÑADIDAS MANUALMENTE ---")
            for nombre_manual, ruta_manual in sorted(self.manuales.items()):
                if nombre_manual in self.ocultos:
                    continue
                juegos_encontrados_global.add(nombre_manual)
                ind = "[👍 Copia Ok] " if self.check_bkp(nombre_manual) else "               "
                tam_str = self.get_folder_size_str(ruta_manual)
                nv = f"{ind}{nombre_manual} ({tam_str})"
                self.juegos[nv] = ruta_manual
                elementos_a_insertar.append(nv)
                total_items_detectados += 1

        # Agrupamos por launcher para mostrar bloques ordenados, como antes.
        # Un mismo juego puede tener varias rutas de save resueltas (p. ej.
        # una en AppData y otra en Documents, o varias carpetas de perfil):
        # se agrupan TODAS bajo el mismo nombre para que aparezcan como UNA
        # sola línea en la lista (el tamaño mostrado es la suma de todas), en
        # vez de una línea repetida por cada carpeta encontrada.
        por_launcher = {}
        for nombre, launcher, ruta in encontrados:
            por_launcher.setdefault(launcher, {}).setdefault(nombre, []).append(ruta)

        iconos_launcher = {"Steam": "📂", "Epic": "🟣", "GOG": "🟪", "Battle.net": "🔷",
                           "Ubisoft": "🔵", "Carpeta": "📁"}
        for launcher in sorted(por_launcher.keys()):
            nombres_launcher = sorted(por_launcher[launcher].keys(), key=str.lower)
            elementos_carpeta = []
            for nombre in nombres_launcher:
                if nombre in self.ocultos or nombre in juegos_encontrados_global:
                    continue
                elementos_carpeta.append((nombre, por_launcher[launcher][nombre]))
            if not elementos_carpeta:
                continue
            icono = iconos_launcher.get(launcher, "🎮")
            nombre_visual_launcher = NOMBRE_VISUAL_LAUNCHER.get(launcher, launcher)
            elementos_a_insertar.append("")
            elementos_a_insertar.append(f"--- {icono} {nombre_visual_launcher.upper()} ---")
            for nombre, rutas in elementos_carpeta:
                juegos_encontrados_global.add(nombre)
                ind = "[👍 Copia Ok] " if self.check_bkp(nombre) else "               "
                tam_str = self.get_rutas_size_str(rutas)
                nv = f"{ind}{nombre} ({tam_str} · {nombre_visual_launcher})"
                # Si hay más de una carpeta real para este juego, se guardan
                # todas: al respaldar/restaurar se procesan las dos, aunque
                # en la lista cuenten y se vean como un único elemento.
                self.juegos[nv] = rutas[0] if len(rutas) == 1 else rutas
                elementos_a_insertar.append(nv)
                total_items_detectados += 1

        # instalados cuya ficha del manifest SÍ cruzó y SÍ resolvió una ruta,
        # pero esa carpeta todavía no existe en disco (típicamente: el juego
        # está instalado pero nunca se ha ejecutado en este Windows, así que
        # aún no ha creado su carpeta de guardado). Se muestran aparte, con
        # la ruta exacta donde aparecerá en cuanto lo abras/juegues una vez.
        previstos_filtrado = [
            (nombre, launcher, ruta) for nombre, launcher, ruta in previstos
            if nombre not in self.ocultos and nombre not in juegos_encontrados_global
        ]
        if previstos_filtrado:
            # Igual que en "encontrados": si el mismo juego tiene varias
            # rutas previstas, se fusionan y solo se muestra/cuenta una vez.
            por_launcher_prev = {}
            for nombre_real, launcher, ruta in previstos_filtrado:
                por_launcher_prev.setdefault(launcher, {}).setdefault(nombre_real, []).append(ruta)

            elementos_a_insertar.append("")
            elementos_a_insertar.append("═══ 📌 INSTALADOS - RUTA PREVISTA (aún no creada, ábrelo/juega una vez) ═══")

            for launcher in sorted(por_launcher_prev.keys()):
                icono = iconos_launcher.get(launcher, "🎮")
                nombre_visual_launcher = NOMBRE_VISUAL_LAUNCHER.get(launcher, launcher)
                elementos_a_insertar.append(f"--- {icono} {nombre_visual_launcher.upper()} (ruta prevista) ---")
                for nombre_real in sorted(por_launcher_prev[launcher].keys(), key=str.lower):
                    rutas = por_launcher_prev[launcher][nombre_real]
                    juegos_encontrados_global.add(nombre_real)
                    if len(rutas) == 1:
                        nv = f"               {nombre_real} → se creará en: {rutas[0]}"
                    else:
                        nv = f"               {nombre_real} → se creará en: {rutas[0]} (+{len(rutas) - 1} más)"
                    self.juegos[nv] = ""  # carpeta aún no existe: solo informativo, no respaldable todavía
                    elementos_a_insertar.append(nv)
                    total_items_detectados += 1

        # instalados cuya ficha del manifest SÍ cruzó (Ludusavi conoce el
        # juego), pero esa ficha no tiene ninguna ruta marcada como 'save'
        # para Windows: no es un fallo de detección, es que Ludusavi no
        # tiene constancia de que ese juego guarde partida en disco (típico
        # de shooters competitivos como Counter-Strike 2, o de juegos sin
        # sistema de guardado como tal, p. ej. PEAK). Se muestran aparte
        # para no confundirlos con los realmente "no reconocidos".
        sin_datos_filtrado = [
            (nombre, launcher) for nombre, launcher in sin_datos
            if nombre not in self.ocultos and nombre not in juegos_encontrados_global
        ]
        if sin_datos_filtrado:
            por_launcher_sd = {}
            for nombre_real, launcher in sin_datos_filtrado:
                por_launcher_sd.setdefault(launcher, []).append(nombre_real)

            elementos_a_insertar.append("")
            elementos_a_insertar.append("═══ ℹ️ SIN DATOS DE GUARDADO CONOCIDOS (la base de datos no registra save para estos) ═══")

            for launcher in sorted(por_launcher_sd.keys()):
                icono = iconos_launcher.get(launcher, "🎮")
                nombre_visual_launcher = NOMBRE_VISUAL_LAUNCHER.get(launcher, launcher)
                elementos_a_insertar.append(f"--- {icono} {nombre_visual_launcher.upper()} (sin datos de guardado) ---")
                for nombre_real in sorted(por_launcher_sd[launcher], key=str.lower):
                    juegos_encontrados_global.add(nombre_real)
                    nv = f"               {nombre_real} (instalado · sin save conocido)"
                    self.juegos[nv] = ""  # informativo: no hay ruta de save que respaldar
                    elementos_a_insertar.append(nv)
                    total_items_detectados += 1

        # A petición del usuario: los juegos instalados de los que NO se pudo
        # localizar ninguna carpeta de saves ("sin_localizar") ya NO se
        # muestran en la lista. Siguen detectándose por debajo (por eso
        # localizar_saves_instalados() los sigue devolviendo, y siguen
        # contando en el resumen de launchers de arriba), pero se omiten
        # aquí en vez de mostrarse bajo "🎮 INSTALADOS SIN LOCALIZAR". Si
        # quieres respaldar uno de esos juegos igualmente, usa
        # "➕ Añadir Manual" para indicar su carpeta a mano.
        _ = sin_localizar  # variable ya no se usa para mostrar nada en pantalla

        lista_solo_backup = []
        for juego_bkp in list(self.backups_existentes):
            if juego_bkp not in [x.lower() for x in juegos_encontrados_global] and juego_bkp not in [x.lower() for x in self.ocultos]:
                nombre_visual = juego_bkp
                ruta_antigua_bkp = os.path.join(self.dest, juego_bkp)
                if os.path.exists(ruta_antigua_bkp):
                    try:
                        nombre_visual = os.listdir(self.dest)[list(self.backups_existentes).index(juego_bkp)]
                    except Exception:
                        pass
                lista_solo_backup.append(nombre_visual)
        if lista_solo_backup:
            lista_solo_backup.sort(key=lambda s: s.lower())
            elementos_a_insertar.append("")
            elementos_a_insertar.append("--- 💾 SOLO EN CARPETA BACKUP (DESINSTALADOS) ---")
            for bkp_item in lista_solo_backup:
                r_c = os.path.join(self.dest, bkp_item).replace("\\", "/")
                tam_str = self.get_folder_size_str(r_c)
                nv = f"[👍 Copia Ok] [Solo en Backup] {bkp_item} ({tam_str})"
                self.juegos[nv] = os.path.join(UP, f"Documents/{bkp_item}").replace("\\", "/")
                elementos_a_insertar.append(nv)
                total_items_detectados += 1

        def actualizar_interfaz_grafica():
            for item in elementos_a_insertar:
                self.box.insert(tk.END, item)
            self.lbl_i.config(text=f"Partidas detectadas ({total_items_detectados}):",
                              fg="#1abc9c" if total_items_detectados else "white")
            self.btn_scan.config(state="normal", text="🔍 ESCANEAR SAVES")

        self.root.after(0, actualizar_interfaz_grafica)

    def __init__(self, root):
        self.root = root
        root.title("Gestor de partidas guardadas by nox.bat")
        root.geometry("820x900")
        root.minsize(820, 680)
        root.configure(bg="#2c3e50")
        self.centrar_ventana(root, 820, 900)
        self.dest = BKP
        self.juegos = {}
        self.backups_existentes = set()
        self.ocultos = self.load_ocultos(M_O)
        self.manuales = self.load_manuales(M_M)
        # NUEVO: carpetas raíz de juegos sin launcher (DRM-free / portables)
        self.carpetas_sin_launcher = self.load_carpetas(M_C)
        # NUEVO: base de datos de rutas de saves (Arlequin-SaveHub)
        self.manifest = {}
        self.manifest_por_nombre = {}
        self.manifest_por_steam_id = {}
        self.manifest_por_gog_id = {}
        tk.Label(root, text="Gestor de partidas guardadas", font=("Arial", 16, "bold"),
                 fg="#1abc9c", bg="#2c3e50").pack(pady=12)
        f_db = tk.Frame(root, bg="#2c3e50")
        f_db.pack(pady=2, fill="x", padx=20)
        self.lbl_db_status = tk.Label(f_db, text="Ventana lista. Preparando actualización de la base de datos...",
                                      fg="#bdc3c7", bg="#2c3e50", font=("Arial", 9, "italic"))
        self.lbl_db_status.pack(side="left")
        tk.Button(f_db, text="🔄 Actualizar BD", command=lambda: self.ejecutar_en_hilo(
                      lambda: self.actualizar_bd_y_escanear(forzar=True)),
                  bg="#34495e", fg="#1abc9c", font=("Arial", 8, "bold"), bd=0,
                  cursor="hand2", padx=6, pady=1).pack(side="right")
        tk.Button(f_db, text="🩺 Diagnóstico", command=self.diagnostico_juego,
                  bg="#34495e", fg="#e67e22", font=("Arial", 8, "bold"), bd=0,
                  cursor="hand2", padx=6, pady=1).pack(side="right", padx=(0, 6))
        tk.Button(f_db, text="📁 Juegos sin Launcher", command=self.gestionar_carpetas_sin_launcher,
                  bg="#34495e", fg="#9b59b6", font=("Arial", 8, "bold"), bd=0,
                  cursor="hand2", padx=6, pady=1).pack(side="right", padx=(0, 6))
        f_launchers = tk.Frame(root, bg="#2c3e50")
        f_launchers.pack(pady=0, fill="x", padx=20)
        self.lbl_launchers_status = tk.Label(f_launchers, text="Detectando launchers instalados...",
                                             fg="#bdc3c7", bg="#2c3e50", font=("Arial", 9, "italic"))
        self.lbl_launchers_status.pack(side="left")
        f_r = tk.Frame(root, bg="#34495e", bd=1, relief="solid")
        f_r.pack(pady=5, fill="x", padx=20, ipady=5)
        self.lbl_r = tk.Label(f_r, text=f" Guardando en: {self.dest}", fg="#bdc3c7", bg="#34495e",
                              font=("Arial", 9), wraplength=420, justify="left")
        self.lbl_r.pack(side="left", fill="x", expand=True, padx=5)
        f_r_btns = tk.Frame(f_r, bg="#34495e")
        f_r_btns.pack(side="right", padx=5)
        tk.Button(f_r_btns, text="Abrir", command=self.abrir_carpeta_backups, bg="#3498db",
                  fg="white", font=("Arial", 8, "bold"), bd=0, cursor="hand2", padx=8, pady=2).pack(side="top", pady=2)
        tk.Button(f_r_btns, text="Cambiar", command=self.cambiar_carpeta, bg="#1abc9c",
                  fg="white", font=("Arial", 8, "bold"), bd=0, cursor="hand2", padx=8, pady=2).pack(side="top", pady=2)
        f_s = tk.Frame(root, bg="#2c3e50")
        f_s.pack(pady=8, fill="x", padx=20)
        self.lbl_i = tk.Label(f_s, text="Partidas detectadas (0):", font=("Arial", 11, "bold"),
                              fg="white", bg="#2c3e50")
        self.lbl_i.pack(side="left")
        f_s_btns = tk.Frame(f_s, bg="#2c3e50")
        f_s_btns.pack(side="right")
        tk.Button(f_s_btns, text="➕ Añadir Manual", command=self.añadir_carpeta_manual, bg="#9b59b6",
                  fg="white", font=("Arial", 9, "bold"), bd=0, padx=8, pady=4, cursor="hand2").pack(side="left", padx=2)
        tk.Button(f_s_btns, text="➖ Quitar Manual", command=self.quitar_carpeta_manual, bg="#e67e22",
                  fg="white", font=("Arial", 9, "bold"), bd=0, padx=8, pady=4, cursor="hand2").pack(side="left", padx=2)
        self.btn_scan = tk.Button(f_s_btns, text="🔍 ESCANEAR SAVES",
                                  command=lambda: self.ejecutar_en_hilo(self.scan),
                                  bg="#3498db", fg="white", font=("Arial", 9, "bold"), bd=0,
                                  padx=8, pady=4, cursor="hand2")
        self.btn_scan.pack(side="left", padx=2)
        self.box = tk.Listbox(root, font=("Arial", 11), bg="#34495e", fg="white",
                              selectbackground="#1abc9c", bd=0, highlightthickness=0,
                              activestyle="none", selectmode="multiple")
        self.box.pack(pady=5, padx=20, fill="both", expand=True)
        f_v = tk.Frame(root, bg="#2c3e50")
        f_v.pack(pady=4, fill="x", padx=20)
        tk.Button(f_v, text="🙈 Ocultar seleccionado(s)", font=("Arial", 9, "bold"), bg="#2c3e50",
                  fg="#e67e22", bd=0, activebackground="#2c3e50", activeforeground="#d35400",
                  cursor="hand2", command=self.hide).pack(side="left", fill="x", expand=True)
        tk.Button(f_v, text="👀 Gestionar Ocultos", font=("Arial", 9, "bold"), bg="#2c3e50",
                  fg="#3498db", bd=0, activebackground="#2c3e50", activeforeground="#2980b9",
                  cursor="hand2", command=self.mostrar_submenu_ocultos).pack(side="right", fill="x", expand=True)
        f_m = tk.Frame(root, bg="#2c3e50")
        f_m.pack(pady=4, fill="x", padx=20)
        f_m.columnconfigure(0, weight=1, uniform="grupo_botones")
        f_m.columnconfigure(1, weight=1, uniform="grupo_botones")
        btn_sel = tk.Button(f_m, text="☑️ Seleccionar Todos", font=("Arial", 10, "bold"), bg="#9b59b6",
                            fg="white", bd=0, relief="flat", pady=8, cursor="hand2",
                            command=self.seleccionar_todo_el_listado)
        btn_sel.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        btn_desel = tk.Button(f_m, text="🔲 Deseleccionar Todos", font=("Arial", 10, "bold"), bg="#95a5a6",
                              fg="black", bd=0, relief="flat", pady=8, cursor="hand2",
                              command=self.deseleccionar_todo_el_listado)
        btn_desel.grid(row=0, column=1, sticky="ew", padx=(3, 0))
        f_b = tk.Frame(root, bg="#2c3e50")
        f_b.pack(pady=4, fill="x", padx=20)
        f_b.columnconfigure(0, weight=1, uniform="grupo_botones")
        f_b.columnconfigure(1, weight=1, uniform="grupo_botones")
        btn_resp = tk.Button(f_b, text="💾 Respaldar Save(s)", font=("Arial", 11, "bold"), bg="#2ecc71",
                             fg="white", bd=0, relief="flat", pady=8, cursor="hand2",
                             command=lambda: self.ejecutar_en_hilo(lambda: self.op(1)))
        btn_resp.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        btn_rest = tk.Button(f_b, text="🔄 Restaurar Save(s)", font=("Arial", 11, "bold"), bg="#e74c3c",
                             fg="white", bd=0, relief="flat", pady=8, cursor="hand2",
                             command=lambda: self.ejecutar_en_hilo(lambda: self.op(2)))
        btn_rest.grid(row=0, column=1, sticky="ew", padx=(3, 0))
        f_inf = tk.Frame(root, bg="#2c3e50")
        f_inf.pack(pady=15, fill="x", padx=20)
        tk.Button(f_inf, text="🎁 Donar", command=self.abrir_link_donar, bg="#e67e22", fg="white",
                  font=("Arial", 10, "bold"), bd=0, padx=15, pady=6, cursor="hand2").pack(side="left")
        tk.Button(f_inf, text="➡️ X (Twitter)", command=self.abrir_link_contacto, bg="#d35400", fg="white",
                  font=("Arial", 10, "bold"), bd=0, padx=15, pady=6, cursor="hand2").pack(side="left", padx=10)
        tk.Button(f_inf, text="🚪 Salir", command=root.quit, bg="#7f8c8d", fg="white",
                  font=("Arial", 10, "bold"), bd=0, padx=15, pady=6, cursor="hand2").pack(side="right")
        tk.Label(f_inf, text="by nox.bat", font=("Arial", 11, "bold", "italic"),
                 fg="#bdc3c7", bg="#2c3e50").pack(pady=4)
        # IMPORTANTE: la ventana ya está construida y a punto de mostrarse
        # (root.mainloop() se llama justo después, fuera de esta clase).
        # Solo AHORA, en un hilo aparte para no bloquear la interfaz, se
        # descarga/actualiza la base de datos de Arlequin-SaveHub y se escanea.
        self.ejecutar_en_hilo(self.indexar_backups_en_disco)
        self.ejecutar_en_hilo(lambda: self.actualizar_bd_y_escanear(forzar=False))


if __name__ == "__main__":
    root = tk.Tk()
    app = GestorPartidasLocal(root)
    root.mainloop()
