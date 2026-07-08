<p align="center">
  <img src="assets/logo-v3-1024.png" width="140" alt="Butler">
</p>

<h1 align="center">Butler</h1>

<p align="center">
  <a href="README.md">English</a> · <a href="README.zh-CN.md">简体中文</a> · <a href="README.ja.md">日本語</a> · <a href="README.ko.md">한국어</a> · Español
</p>

<p align="center"><b>Un gestor de proyectos creado para vibecoding multihilo.</b><br>
Para personas con cerebro ADHD que ejecutan Claude Code y Codex en paralelo: tu viejo mayordomo para cada agent, thread y siguiente paso.</p>

<p align="center">
  <code>Claude Code</code> · <code>Codex</code> · <code>ADHD-friendly</code> · <code>menu-bar</code> · <code>multi-project</code> · <code>macOS</code>
</p>

<p align="center">
  <a href="assets/demo.mp4?raw=1"><img src="assets/demo-poster.png" width="720" alt="Watch Butler demo video"></a><br>
  <sub>Haz click en la vista previa para ver el video demo.</sub>
</p>

---

## El problema

Cuando ejecutas varios AI coding agents en paralelo (Claude Code, Codex…), lo primero que se pierde no es el código, sino el contexto:

- **olvidas qué sesión está esperando por ti**;
- **olvidas hasta dónde llegó cada proyecto**;
- **no sabes cuál importa más**;
- y al día siguiente **no sabes por dónde empezar**.

Un recordatorio normal no basta. Te avisa, pero no conserva progreso, estado ni prioridad.

Trabajar con agents se parece a repartir pedidos: pasas ratos esperando y, de pronto, llega una entrega que exige acción inmediata. El trabajo profundo se parte en fragmentos pequeños, algo especialmente duro para cerebros con ADHD.

Butler mantiene cerca el contexto que se pierde: el propósito inicial de cada proyecto, el progreso actual, los últimos 3 intercambios y el orden de prioridad. La meta no es exprimir más agent credits, sino proteger lo que esos credits no pueden comprar de vuelta: tu tiempo.

**Butler es el mayordomo de tu trabajo con agents en paralelo.** No hace el trabajo por ti; evita que se te caigan los hilos.

## Qué hace

| Superficie | Qué te da |
|---|---|
| **▦ Badge en la barra de menú** | `▦ 2` = 2 sesiones esperando por ti; `▦ ·` = algo está corriendo; `▦` = todo tranquilo. Una mirada y tienes el mapa completo. |
| **Popover** (click en ▦) | Las tarjetas en espera tienen un brillo amber respirando; las nuevas hacen un pequeño pulse. Renombra, define el propósito inicial del proyecto, prioridad, archiva o copia el nombre ahí mismo. |
| **Mini tarjeta de escritorio** | Una tarjeta de 232px fijada al escritorio: sobre el wallpaper, bajo tus ventanas, sin estorbar, para mantener visible lo más prioritario. Puedes fijarla arriba o arrastrarla. |
| **Notificaciones del sistema** | Cuando un agent pasa de running a waiting, Butler te avisa con la última línea del agent: tu siguiente paso ya preparado. Notificaciones nativas de macOS, icono correcto, sin spam y con resumen diario. |
| **Tablero completo** | Arrastra entre columnas, tabs de Claude/Codex, prioridades P0/P1/P2, propósito del proyecto y recap de los últimos 3 eventos para recordar qué estabas haciendo. |
| **Butler Light companion** | Companion opcional para tiras LED ELK-BLEDOM. Butler escribe un JSON local pequeño y Butler Light convierte Waiting > Running > Shelved en colores. |

### El modelo: inbox zero para agents

- **Running / Waiting = hechos**: es el estado real del agent. Si se detuvo hace una hora, sigue esperando por ti.
- **Shelved = tu decisión**: solo sale del inbox cuando tú lo archivas.
- **Scheduled / cron sessions**: aparecen mientras corren y desaparecen al terminar. No fingen ser tareas pendientes.
- **P0/P1/P2**: ordenan tu lista de waiting para que la primera tarjeta de la mañana sea el punto de entrada.

## Instalación

> Butler no está notarizado. macOS puede mostrar “unidentified developer”. Es normal: ábrelo una vez con **click derecho → Open**, y luego se abrirá normalmente.

Requiere macOS 13+, Xcode Command Line Tools (`xcode-select --install`) y Node (para Claude session hooks).

```bash
git clone https://github.com/YOUR_USER/agent-butler.git ~/dev/agent-butler
bash ~/dev/agent-butler/native/build.sh          # compila → /Applications/Butler.app → lanza
```

`build.sh` compila la app Swift, la empaqueta e instala los Claude session hooks. La primera notificación pedirá permiso; acéptalo. Puedes activar **Login at startup** desde el menú.

Las únicas piezas externas son los Claude session hooks (instalados automáticamente) y el `python3` del sistema. No necesitas pip, venv ni Homebrew.

## Grabación: Demo Mode

Para capturas, demos y videos de lanzamiento, haz click derecho en el icono `▦` de la barra de menú y activa **Demo Mode**.

Demo Mode muestra un conjunto fijo de proyectos falsos de Claude/Codex y no lee tus sesiones reales, transcripts, rutas, nombres de proyectos ni notas. Puedes renombrar tarjetas, editar notas de propósito, cambiar prioridades y arrastrar tarjetas entre columnas; esos cambios se guardan solo en `~/.claude-monitor/demo-extras.json`. El badge de la barra de menú, el popover, el mini board, el board completo y el puente de estado de Butler Light usan los mismos datos falsos hasta que desactives Demo Mode.

## Opcional: Butler Light

Butler Light es una app companion nativa para macOS que controla tiras LED compatibles con ELK-BLEDOM. Está separada a propósito: Butler se mantiene pequeño y enfocado; Bluetooth, vinculación de dispositivo y color viven en el companion.

```bash
cd ~/dev/agent-butler/butler-light
./scripts/package_app.sh
open "dist/Butler Light.app"
```

Abre Butler Light, permite Bluetooth, vincula tu tira y elige el modo **Butler Status**. Lee este archivo:

```text
~/.claude-monitor/butler-light-status.json
```

La prioridad siempre es **Waiting > Running > Shelved**. Puedes cambiar cada color en el companion o usar **Fixed Color** para control manual.

## Arquitectura

```text
/Applications/Butler.app   Swift nativo, self-contained
├─ Butler                  barra de menú / popover / mini / notificaciones nativas
│                          / login item / gestiona el server subprocess
└─ Resources/
   ├─ server.py            motor de datos stdlib-only:
   │                         Claude session hooks + transcript heartbeat
   │                         parsing de Codex ~/.codex/sessions
   │                         priority / purpose / archive storage · popover / mini / board HTML
   └─ AppIcon.icns

butler-light/              companion Swift opcional:
├─ BLE scan / bind / ELK-BLEDOM RGB write
├─ fixed color mode
└─ Butler status mode vía ~/.claude-monitor/butler-light-status.json
```

## Privacidad

Butler corre completamente en tu máquina y solo lee tus propios datos locales de agents (`~/.claude`, `~/.codex`, session transcripts). Butler Light solo usa Bluetooth local y el JSON local de estado. No hay servidor, telemetry ni cuenta.

## Localización

El README está disponible en **English / 简体中文 / 日本語 / 한국어 / Español**.

La UI de Butler viene en inglés por defecto e incluye chino, japonés, coreano y español. El nombre de la app también se localiza: Butler · 老管家 · バトラー · 집사.

## License

MIT — see [LICENSE](LICENSE).
