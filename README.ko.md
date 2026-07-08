<p align="center">
  <img src="assets/logo-v3-1024.png" width="140" alt="Butler">
</p>

<h1 align="center">Butler</h1>

<p align="center">
  <a href="README.md">English</a> · <a href="README.zh-CN.md">简体中文</a> · <a href="README.ja.md">日本語</a> · 한국어 · <a href="README.es.md">Español</a>
</p>

<p align="center"><b>멀티스레드 vibecoding을 위해 만든 프로젝트 관리 도구.</b><br>
Claude Code와 Codex를 동시에 돌리는 ADHD 성향의 사람들을 위해. 모든 agent, thread, 다음 단계를 챙겨 주는 당신의 오래된 집사입니다.</p>

<p align="center">
  <code>Claude Code</code> · <code>Codex</code> · <code>ADHD-friendly</code> · <code>menu-bar</code> · <code>multi-project</code> · <code>macOS</code>
</p>

https://github.com/user-attachments/assets/dcd7e423-e870-434b-8a9f-a94320bc962a

---

## 문제

여러 AI coding agent(Claude Code, Codex 등)를 동시에 돌리다 보면 코드보다 먼저 맥락을 놓치게 됩니다.

- **어떤 세션이 내 응답을 기다리는지** 잊습니다.
- **각 프로젝트가 어디까지 진행됐는지** 잊습니다.
- **무엇이 가장 중요한지** 판단하기 어렵습니다.
- 다음 날 아침, **어느 프로젝트부터 시작해야 할지** 모릅니다.

일반 알림만으로는 부족합니다. 알림은 울리지만 진행 상황, 상태, 우선순위까지 잡아 주지는 못합니다.

agent 작업은 배달 주문처럼 느껴질 때가 있습니다. 기다리는 시간은 길고 조용하지만, 주문이 들어오면 바로 움직여야 합니다. 깊은 몰입 시간은 잘게 쪼개지고, ADHD 뇌에는 특히 부담이 됩니다.

Butler는 각 프로젝트의 처음 목적, 현재 진행 상황, 최근 3번의 대화, 우선순위를 가까이에 둡니다. 목표는 agent credit을 끝까지 태우는 것이 아니라, credit으로 다시 살 수 없는 시간을 지키는 것입니다.

**Butler는 병렬 agent 작업을 위한 집사입니다.** 대신 일하지는 않지만, 당신이 일을 놓치지 않게 지켜봅니다.

## 기능

| 화면 | 제공하는 것 |
|---|---|
| **▦ 메뉴 막대 배지** | `▦ 2` = 응답 대기 2개, `▦ ·` = 실행 중, `▦` = 모두 조용함. 한눈에 전체 상태를 볼 수 있습니다. |
| **팝오버**(▦ 클릭) | 대기 카드에는 amber 호흡 효과, 새 카드에는 가벼운 pulse. 이름 변경, 프로젝트의 처음 목적, 우선순위, 보류, 이름 복사를 바로 처리합니다. |
| **데스크톱 mini 카드** | 232px 카드가 바탕화면 위, 창 아래에 고정됩니다. 가장 우선순위 높은 일을 시야에 남기면서 방해하지 않고, 고정하거나 드래그할 수 있습니다. |
| **시스템 알림** | agent가 running에서 waiting으로 바뀌는 순간, 마지막 출력과 함께 다음 단계를 알려 줍니다. 네이티브 macOS 알림, 올바른 아이콘, 스팸 방지, 일일 요약 포함. |
| **전체 보드** | 컬럼 드래그, Claude/Codex 탭, P0/P1/P2 우선순위, 프로젝트 목적, 최근 3개 recap. 이 프로젝트가 무엇을 위한 것인지 바로 떠올릴 수 있습니다. |
| **Butler Light companion** | 선택형 LED companion. Butler가 작은 로컬 JSON을 쓰고, Butler Light가 Waiting > Running > Shelved를 조명 색으로 바꿉니다. |

### 모델: agent용 inbox zero

- **Running / Waiting = 사실**: agent의 현재 상태입니다. 한 시간 멈춰 있어도 여전히 당신을 기다리는 상태입니다.
- **Shelved = 당신의 결정**: 직접 보류/아카이브해야 inbox에서 빠집니다.
- **Scheduled / cron 세션**: 실행 중일 때만 보이고, 끝나면 사라집니다. 가짜 todo를 만들지 않습니다.
- **P0/P1/P2**: waiting 목록을 정렬해 아침에 첫 카드부터 바로 시작할 수 있게 합니다.

## 설치

> Butler는 notarize되지 않았습니다. macOS가 “unidentified developer”라고 말할 수 있습니다. 처음 한 번만 **우클릭 → Open**으로 열면 이후에는 정상 실행됩니다.

필요: macOS 13+, Xcode Command Line Tools(`xcode-select --install`), Node(Claude session hooks용).

```bash
git clone https://github.com/YOUR_USER/agent-butler.git ~/dev/agent-butler
bash ~/dev/agent-butler/native/build.sh          # compile → /Applications/Butler.app → launch
```

`build.sh`는 Swift app을 컴파일하고 패키징하며 Claude session hooks를 설치합니다. 첫 알림 권한 요청이 뜨면 허용하세요. 메뉴에서 **Login at startup**을 켤 수 있습니다.

외부 요소는 Claude session hooks(자동 설치)와 시스템 `python3`뿐입니다. pip, venv, Homebrew는 필요 없습니다.

## 녹화용: 데모 모드

스크린샷, 데모, 출시 영상을 찍을 때는 메뉴 막대의 `▦` 아이콘을 우클릭하고 **데모 모드**를 켜세요.

데모 모드는 고정된 가짜 Claude/Codex 프로젝트만 보여 주며 실제 세션, transcripts, 경로, 프로젝트 이름, 메모를 읽지 않습니다. 카드 이름, 목적 메모, 우선순위, 컬럼 이동은 그대로 편집할 수 있고, 변경 사항은 `~/.claude-monitor/demo-extras.json`에만 저장됩니다. 메뉴 배지, 팝오버, mini 보드, 전체 보드, Butler Light 상태 브리지는 끄기 전까지 같은 가짜 데이터를 사용합니다.

## 선택: Butler Light

Butler Light는 ELK-BLEDOM 호환 LED 스트립을 위한 독립 macOS companion app입니다. Butler 본체는 작고 집중된 상태로 두고, Bluetooth 권한, 기기 연결, 색상 제어는 companion에 둡니다.

```bash
cd ~/dev/agent-butler/butler-light
./scripts/package_app.sh
open "dist/Butler Light.app"
```

Butler Light를 열고 Bluetooth를 허용한 뒤 스트립을 연결하고 **Butler Status** 모드를 선택하세요. 읽는 파일은 다음입니다.

```text
~/.claude-monitor/butler-light-status.json
```

우선순위는 항상 **Waiting > Running > Shelved**입니다. companion에서 각 상태 색상을 바꿀 수 있고, **Fixed Color**로 전환하면 수동 조명 컨트롤로 사용할 수 있습니다.

## 구조

```text
/Applications/Butler.app   네이티브 Swift, self-contained
├─ Butler                  메뉴 막대 / 팝오버 / mini / 네이티브 알림
│                          / 로그인 항목 / server subprocess 관리
└─ Resources/
   ├─ server.py            stdlib-only 데이터 엔진:
   │                         Claude session hooks + transcript heartbeat
   │                         Codex ~/.codex/sessions parsing
   │                         priority / purpose / archive storage · popover / mini / board HTML
   └─ AppIcon.icns

butler-light/              선택형 Swift companion:
├─ BLE scan / bind / ELK-BLEDOM RGB write
├─ fixed color mode
└─ ~/.claude-monitor/butler-light-status.json을 통한 Butler status mode
```

## 개인정보

Butler는 완전히 로컬에서 실행되며, 당신 자신의 agent 데이터(`~/.claude`, `~/.codex`, session transcripts)만 읽습니다. Butler Light는 로컬 Bluetooth와 로컬 status JSON만 사용합니다. 서버, telemetry, 계정은 없습니다.

## 현지화

README는 **English / 简体中文 / 日本語 / 한국어 / Español**을 제공합니다.

Butler app UI는 영어가 기본이며 중국어, 일본어, 한국어, 스페인어가 포함되어 있습니다. 앱 이름도 Butler · 老管家 · バトラー · 집사로 현지화됩니다.

## License

MIT — see [LICENSE](LICENSE).
