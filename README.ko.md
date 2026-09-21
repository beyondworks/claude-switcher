# Claude Switcher

**키 하나로 Claude 데스크톱 앱의 계정을 바꾸고, 어느 계정에서든 같은 Code 세션을 이어서 씁니다.**

<p>
  <img src="docs/menubar-a.png" width="480" alt="메뉴 막대 — A 계정(주황)"><br>
  <img src="docs/menubar-b.png" width="480" alt="메뉴 막대 — B 계정(청록)">
</p>

`⌘ Page Down`을 누르면 지금 계정의 앱이 꺼지고, 다음 계정의 앱이 로그인된 상태로 열립니다.
사이드바에는 방금 보던 세션이 그대로 있습니다. 로그아웃하거나 다시 로그인할 필요가 없고, 작업 기록도 둘로 갈라지지 않습니다.

[English README](README.md)

> Anthropic과 관계없는 비공식 커뮤니티 도구입니다. 지금은 macOS만 지원합니다.

---

## 원리: 세 가지 사실

Claude Switcher는 앱을 뜯어고치지 않습니다. 앱이 원래 하는 세 가지를 정리해서 쓸 뿐입니다.

1. **데이터 폴더마다 로그인이 따로 저장됩니다.** 데스크톱 앱은 다른 데이터 폴더(`--user-data-dir`)로 띄울 수 있고,
   폴더마다 그 폴더에서 로그인한 계정을 기억합니다. 그래서 계정마다 폴더를 하나씩 두면 모든 계정이 로그인된 채로 남습니다.
2. **대화 내용은 이미 공유됩니다.** Code 탭의 대화 기록은 `~/.claude/projects` 한 곳에 계정과 상관없이 저장됩니다.
   계정별로 나뉘는 것은 사이드바 목록뿐입니다. 위치는 `<데이터 폴더>/claude-code-sessions/<계정>/<조직>/`입니다.
3. **그래서 목록만 똑같이 맞춥니다.** 작은 백그라운드 작업이 계정 폴더 사이의 목록 변경을 몇 초 안에 서로 옮깁니다.
   앱은 한 번에 한 계정만 켜지므로, 두 곳에서 동시에 기록할 일이 없습니다.

<p align="center"><img src="docs/how-it-works.svg" width="720" alt="동작 구조"></p>

전환은 결국 이 세 단계입니다. *지금 계정 앱 종료 → 목록 한 번 맞추기 → 다음 계정 폴더로 앱 열기.*

## 기능

| | |
|---|---|
| **⌘ Page Down** | 어디서든 다음 계정으로 전환합니다(A → B → C … → A). |
| **메뉴 막대** | 계정마다 다른 색의 Claude 심볼로 지금 켜진 계정을 보여 줍니다. 메뉴에서 원하는 계정을 고를 수 있습니다. |
| **`claude-switch`** | 터미널이나 Claude 세션 안에서 같은 동작을 합니다. |
| **작업 중 확인** | 아직 작업 중인 세션이 있으면 "작업 중인 세션이 N개 있습니다. 그래도 전환할까요?"를 먼저 묻습니다. |
| **계정 개수 제한 없음** | `claude-switch add`로 C, D, …를 추가하고, 계정마다 다른 색을 씁니다. |
| **마지막 계정으로 켜기** | Dock 아이콘, 로그인 자동 실행, 재부팅으로 앱을 켜면 항상 기본 계정(A)으로 열립니다. 마지막에 쓴 계정이 다르면 곧바로 그 계정으로 다시 엽니다. 끄려면 `~/.config/claude-switcher/config.json`에 `"restore_last": false`를 넣으세요. |

<p align="center"><img src="docs/menu.png" width="360" alt="메뉴 막대 메뉴"></p>

메뉴 막대 심볼은 실행할 때 **사용자 맥에 설치된** `/Applications/Claude.app` 아이콘에서 뽑아 색을 입힙니다.
이 저장소에는 Anthropic의 로고 파일이 들어 있지 않습니다. 아이콘을 읽지 못하면 직접 그린 별 모양을 대신 씁니다.

## 설치

필요한 것: macOS, `/Applications`에 설치된 Claude 데스크톱 앱, Xcode Command Line Tools(`xcode-select --install`).

```bash
git clone https://github.com/beyondworks/claude-switcher.git
cd claude-switcher
./install.sh
```

설치 스크립트는 다음을 합니다.
- `claude-switch`를 `~/.local/bin`에 넣습니다.
- 메뉴 막대 앱을 빌드해 `~/Applications`에 두고, 로그인할 때 자동으로 켜지게 합니다.
- 지금 계정의 세션 폴더를 찾아 둡니다.

### 두 번째 계정 추가 (처음 한 번)

```bash
claude-switch add 개인     # 자기 데이터 폴더를 쓰는 두 번째 Claude 창이 열립니다
```

그 창에서 한 번 로그인하고 **Code** 탭을 한 번 연 뒤, 다음을 실행합니다.

```bash
claude-switch setup        # 새 계정의 세션 폴더를 찾아 동기화를 시작합니다
```

> **구글 로그인 주의.** 다른 Claude 창이 떠 있으면, 브라우저가 구글 로그인 결과를 *그 창*으로 넘깁니다.
> 그 창은 이 결과를 무시하므로 새 창은 로그인되지 않습니다. 새 창에서는 **이메일 로그인**을 쓰시거나, 로그인하는 동안만
> 다른 Claude 창을 종료해 주세요. 로그인은 그 계정 폴더에 저장되므로 이 과정은 처음 한 번만 필요합니다.

메뉴에 보일 계정 이름을 정합니다.

```bash
claude-switch label a 업무
claude-switch label b 개인
```

## 사용

```bash
claude-switch            # 다음 계정으로
claude-switch b          # 특정 계정으로
claude-switch status     # 지금 켜진 계정
claude-switch profiles   # 계정 목록
claude-switch doctor     # 폴더와 동기화 작업 점검
```

## 공유되는 것과 공유되지 않는 것

| 계정끼리 공유됨 | 공유되지 않음 |
|---|---|
| Code 탭 세션 목록(이름, 보관, 삭제) | claude.ai 웹 채팅(계정별로 Anthropic 서버에 저장) |
| 대화 기록(`~/.claude/projects`) | Cowork(로컬 에이전트) 세션 |
| 세션 목록과 함께 저장되는 루틴 | 사용 한도와 결제(계정마다 따로) |
| | **프롬프트 캐시**: 캐시는 조직 단위로 격리됩니다. 그래서 전환 후 첫 메시지는 캐시 없이 대화를 다시 읽고, 그 계정의 사용량을 더 씁니다 |

## 안전장치

- **바로 지우지 않습니다.** 한 계정에서 지운 세션은 다른 계정 쪽에서도 빠지지만,
  실제로는 `~/Library/Application Support/claude-switcher/trash/<날짜>/`로 옮겨집니다.
- **대량 삭제 방지.** 한 번의 동기화가 전체의 20%를 넘는(그리고 5개가 넘는) 파일을 지우게 되면, 멈추고 기록만 남깁니다.
- **실제 폴더만 씁니다.** 앱은 세션 폴더가 심볼릭 링크이면 저장을 거부합니다(`O_NOFOLLOW`로 엽니다).
  그래서 Claude Switcher는 폴더를 연결하지 않고 복사합니다.
- **한 번에 한 계정만 켭니다.** 두 계정 이상이 켜져 있으면 전환하지 않습니다. 앱을 강제로 끄지 않고, 정상 종료를 최대 30초 기다립니다.
- 전환 직전 몇 초 안에 한 변경은 아직 넘어가지 않았을 수 있습니다. 그래서 전환할 때 동기화를 한 번 더 실행합니다.

## 삭제

```bash
./uninstall.sh
```

프로그램과 백그라운드 작업만 지웁니다. Claude 데이터 폴더, 로그인, 세션은 그대로 둡니다.

## 한계

- macOS만 지원합니다. 윈도우는 시험하지 않았습니다.
- 데스크톱 앱의 현재 폴더 구조와 로그 형식에 기대고 있습니다. 앱이 업데이트되면서 바뀔 수 있고, 그때는 `claude-switch doctor`에 나타납니다.
- 여러 계정을 쓰는 것은 Anthropic 약관의 적용을 받습니다. 쓰시는 요금제 기준으로
  [이용 정책](https://www.anthropic.com/legal/aup)과 [소비자 약관](https://www.anthropic.com/legal/consumer-terms)을 확인해 주세요.

## 개발

```bash
python3 -m unittest discover tests      # 동기화 엔진, 폴더 찾기 시험
swiftc -O menubar/main.swift -o /tmp/ClaudeSwitcher
```

릴리스는 태그를 올리면 만들어집니다. `git tag v0.1.0 && git push origin v0.1.0`

## 라이선스

MIT
