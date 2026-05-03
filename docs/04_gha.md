<!-- docs/04_gha.md -->

# GitHub Action Mechanic

This Document delineates the architecture and internal mechanisms of `src/gha`, which empowers you to execute the `gflzirc` automation routines via **GitHub Actions (GHA)**, serving as a headless, 24/7 cloud solution.

Alternatively, we provided another bash script -- `gfl_farm.sh` -- to allow you to trigger this "GHA" architecture on your own private server instances.

## 1. Design Logic

We engineered the GHA workflow heavily upon the **"Let it wrong"** philosophy. Simply put, we **DO NOT** implement exhaustive defensive boundaries or deep condition checks for raw server errors (e.g., throwing `Error: Unexpected plaintext response`). By allowing localized failures to bubble up and naturally reset the macro loops, our architecture remains significantly simpler, cleaner.

The project architecture is decoupled into distinct modules:

```sh
# GHA workflow 
.github/workflows/gfl_farm.yml
# or bash
.gfl_farm.sh

# Python
src/gha/.
├── agent.py
├── missions
│   ├── base.py
│   ├── epa.py
│   ├── f2p_pr.py
│   ├── f2p.py
│   ├── __init__.py
│   ├── pick_and_train.py
│   └── pick_coin.py
├── parser
│   ├── base.py
│   ├── coin.py
│   ├── index_to_epa.py
│   ├── __init__.py
│   └── skill.py
└── request
    ├── base.py
    ├── index.py
    └── __init__.py
```

### 1.1 agent.py

The `GFLAgent` acts as the supreme orchestrator of the automated workflow. It bridges the gap between the GitHub Actions environment and the game server. Its primary responsibilities include:

1. **Secret Slicing & Injection:** It securely parses minified JSON arrays from GHA Secrets, intelligently indexing specific multi-account configurations to circumvent GitHub's aggressive multiline secret masking bug.
2. **Dynamic Bootstrapping:** Before launching any mission, the agent dynamically fetches server data (via the `request` module) to inject real-time state into the configuration, completely eliminating the need for manual configuration updates when T-Dolls level up.
3. **Infinite Lifecycle Management:** It monitors the absolute execution time. Prior to hitting GHA's strict 6-hour job termination limit, the agent triggers a soft timeout (at 5.5 hours), writes a `respawn.flag`, safely retires pending dolls, and exits gracefully. The outer workflow then detects this flag and dispatches the subsequent job recursively.
4. **Telemetry Dashboard:** It dynamically renders an overarching Markdown report utilizing `GITHUB_STEP_SUMMARY`, allowing users to monitor farming yields in real-time.

### 1.2 missions

The `missions` directory encapsulates the precise tactical maneuvers required for different game maps. Built upon the `BaseMission` interface, each handler strictly exposes two life-cycle methods:

1. **`prepare()`**: Executed during the pre-flight phase. It conducts rigorous echelon validations (e.g., ensuring a strictly single-doll formation for 10352) and builds execution queues (e.g., skill training candidates) prior to entering the massive macro loop.
2. **`farm()`**: Represents the atomic combat sequence. It handles node routing, combination info syncing, and battle finish requests. 

This sandboxed design ensures that the idiosyncratic routing logic of specific maps (e.g., `10352` vs `145`) does not pollute the global agent loop.

### 1.3 parser

Parsers are designed to distill monolithic server JSON payloads into concise, actionable data structures. 

Instead of polluting the mission logic with deep dictionary traversals, parsers isolate complex business rules. For instance, the `SkillTrainParser` encapsulates the complex evaluation of whether a T-Doll possesses an unlocked Skill 2 by calculating if its total EXP strictly exceeds the `10,448,800` threshold. Meanwhile, `CoinParser` abstracts the extraction of training data drops, flawlessly handling both flat and nested JSON node structures.

### 1.4 request

The `request` module abstracts autonomous API invocations independent of the standard combat sequence, such as querying the `Index/index` endpoint.

By sequestering these calls into dedicated classes, we maintain the "Stateless" paradigm of our headless runners. It allows the architecture to fetch the real-time Commander state dynamically, ensuring that components like auto-skill training and EPA echelon rotation operate upon the absolute latest game data.

## 2. How to Config

### 2.1 Actions Secrets and Variables

Since we are running GHA on a **public** repository, we must absolutely avoid hardcoding credentials in the code. We manage configurations and credentials via GitHub Secrets.

#### 2.1.1 Generate Personal Access Token (PAT)

The default `GITHUB_TOKEN` provided by Actions does not have the permission to trigger other workflows (to prevent infinite loops). To enable our "Auto-Respawn" mechanism, you need to generate a PAT:

1. Click your GitHub avatar in the top right corner -> `Settings` -> Scroll to the bottom on the left -> `Developer settings` -> `Personal access tokens` -> `Tokens (classic)`.
2. Click `Generate new token (classic)`.
3. Set a descriptive name (e.g., `GFL_WORKFLOW_PAT`), and select `No expiration` for the expiration time (or customize as needed).
4. **Permissions:** Check the **`repo`** scope (Full control of private repositories).
5. After generating, copy the token string starting with `ghp_xxxxxxxxxxxx`.

#### 2.1.2 Repository Configuration

Next, configure the secrets in your forked repository:

Navigate to: `Repo -> Settings -> Secrets and variables -> Actions -> New repository secret`

Add the following 3 `secrets`:

##### Single Account (Legacy/Standard)

1. **Secret Name:** `GH_PAT`
    - **Value:** `ghp_xxxxxxxxx` (The PAT generated in step 2.1.1).
2. **Secret Name:** `GFL_CONFIG`
    - **Value:**
        ```json
        {
            "USER_UID": "12345678",
            "SERVER_KEY": "M4A1",
            "MACRO_LOOPS": 9999,
            "MISSIONS_PER_RETIRE": 50,
            "SQUAD_ID": 111111,
            "TEAM_ID": 1,
            "EPA_TEAMS": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
            "EPA_PER_RETIRE": 10,
            "TICKET_TYPE": 2
        }
        ```
    - **Parameter Explanations:**
        - `USER_UID`: Your in-game Commander UID.
        - `SERVER_KEY`: Server designation (e.g., `"M4A1"` for CN Android Official).
        - `MACRO_LOOPS`: The master loop count (set extremely high, e.g., 9999, as we rely on time limits to auto-respawn).
        - `MISSIONS_PER_RETIRE`: How many runs before triggering auto-retirement for T-Dolls. Adjust based on your armory's available slots.
        - `SQUAD_ID`: The Heavy Ordnance Corps (HOC) ID used for F2P.
        - `TEAM_ID`: The standard Echelon ID used for PickCoin.
        - `EPA_TEAMS`: An array of Echelon IDs designated for EPA training. The agent will fetch their real-time state automatically.
        - `EPA_PER_RETIRE`: Run how many times EPA training then retire once T-Dolls.
        - `TICKET_TYPE`: Specific ticket of **Gray Zone Exploration**: `1` means exploration permits; `2` means resources.
3. **Secret Name:** `GFL_SIGN_KEY`
    - **Value:** The latest `SIGN_KEY` captured via running the `-c` command in the local CLI tool.
4. **Secret Name:** `GFL_USER_DEVICE`
    - **Value:** Your device fingerprint located inside the `micalog` node of the captured payload. It uses the same array slicing logic as the `SIGN_KEY`.

##### Single Account in Array Notation

For consistency, you can also wrap a single account in JSON arrays.

1. Looks like:
    ```json
    [
        {
            "USER_UID": "12345678",
            "SERVER_KEY": "M4A1",
            "MACRO_LOOPS": 9999,
            "MISSIONS_PER_RETIRE": 50,
            "SQUAD_ID": 111111,
            "TEAM_ID": 1,
            "EPA_TEAMS": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
            "EPA_PER_RETIRE": 10,
            "TICKET_TYPE": 2
        }
    ]
    ```
2. Input as:
    ```json
    [{"USER_UID":"12345678","SERVER_KEY":"M4A1","MACRO_LOOPS":9999,"MISSIONS_PER_RETIRE":50,"SQUAD_ID":111111,"TEAM_ID":1,"EPA_TEAMS":[1,2,3,4,5,6,7,8,9,10],"EPA_PER_RETIRE":10,"TICKET_TYPE":2}]
    ```

##### Multiple Accounts

You can farm multiple accounts simultaneously by passing arrays of configurations.

1. Looks like:
    ```json
    [
        {
            "USER_UID": "12345678",
            "SERVER_KEY": "M4A1",
            "MACRO_LOOPS": 9999,
            "MISSIONS_PER_RETIRE": 50,
            "SQUAD_ID": 111111,
            "TEAM_ID": 1,
            "EPA_TEAMS": [1, 2],
            "EPA_PER_RETIRE": 10,
            "TICKET_TYPE": 2
        },
        {
            "USER_UID": "87654321",
            "SERVER_KEY": "RO635",
            "MACRO_LOOPS": 9999,
            "MISSIONS_PER_RETIRE": 50,
            "SQUAD_ID": 222222,
            "TEAM_ID": 1,
            "EPA_TEAMS": [1, 2, 3],
            "EPA_PER_RETIRE": 15,
            "TICKET_TYPE": 2
        }
    ]
    ```
2. Input as:
    ```json
    [{"USER_UID":"12345678","SERVER_KEY":"M4A1","MACRO_LOOPS":9999,"MISSIONS_PER_RETIRE":50,"SQUAD_ID":111111,"TEAM_ID":1,"EPA_TEAMS":[1,2],"EPA_PER_RETIRE":10,"TICKET_TYPE":2},{"USER_UID":"87654321","SERVER_KEY":"RO635","MACRO_LOOPS":9999,"MISSIONS_PER_RETIRE":50,"SQUAD_ID":222222,"TEAM_ID":1,"EPA_TEAMS":[1,2,3],"EPA_PER_RETIRE":15,"TICKET_TYPE":2}]
    ```

### 2.2 Let's run it

1. Login to the GFL game on your device and finish your daily routine.
2. Run the local proxy tool to capture a **fresh** `SIGN_KEY`.
3. On the GitHub repo, go to `Settings -> Secrets` and update the value of `GFL_SIGN_KEY`.
4. Go to the `Actions` tab and select `GFL Auto Farm Workflow` from the left sidebar.
5. Click the `Run workflow` dropdown menu on the right, select your target branch, choose your desired mission (e.g., `f2p`, `pick_coin`, `epa_fifo`), and click the green run button.
6. **Real-time Monitoring:** By clicking on the running Job, you can open the **Summary** page (top left corner or bottom of the log screen) at any time. It dynamically generates a Markdown table showing runtime, macros completed, and total dolls collected.
7. **Infinite Idle:** After reaching the 5.5-hour soft timeout, the script will wrap up the current loop, retire dolls, and use the GitHub CLI to trigger a brand-new job in the background, achieving 24/7 unlimited farming.
8. **Auto Stop:** To stop the workflow, simply log into the game on your device. This will automatically invalidate the current `SIGN_KEY`, causing the GHA script to hit a fatal error circuit breaker and terminate without respawning. Alternatively, manually cancel the queued workflow via the Actions UI.

## 3. Details in Code

In this chapter, we'll describe some details in source code of `src/gha`.

### 3.1 `gent.py`

In `agent.py`, firstly, we import `gflzirc` and dynamic import `winreg`, though have been exclude in `gflzirc/proxy.py` via:

```py
# Cross-platform
try:
    import winreg
    import ctypes
    HAS_WINREG = True
except ImportError:
    HAS_WINREG = False
```

Then we define some constant:

```py
# Constants
MAX_RUNTIME_SEC = 5 * 3600 + 30 * 60  # 5 hours 30 mins
MAX_CONSECUTIVE_ERRORS = 5
```

1. `MAX_RUNTIME_SEC` used to auto kill an retrigger GHA workflow;
2. `MAX_CONSECUTIVE_ERRORS` allow to stop workflow when a certain number of times are accumulated.

In class `GFLAgent`, we have such functions:

1. `__init__()`, constructor:
    - Fetch environment variables
    - Request `index/Index` to get information of GFL accounts
    - Dynamic replace config e.g. echelon, fairy etc.
2. "Helper functions" for **workflow**:
    - `_extract_array_secret`: get multi accounts' secrets;
    - `write_summary`: output result of this time.
3. "Basic functions" for **farm**:
    - `safe_request`: send request to server;
    - `check_step_error`: if server's response is error code;
    - `check_drop_result`: return dropped T-Dolls' UID in `mission_win_result` (mission) or `reward_gun` (battle);
    - `parse_random_node_drop`: print random nodes' result;
    - `retire_guns`: retire T-Dolls.
4. `run()`, farm loop:
    - Run `self.mission_handler.prepare()` first;
    - Then into nested loops:
        * in `micro`, we run missions for `n` times;
        * in `marco`, we retire T-Dolls and do some boundary check;
    - Finally, end loop and write summary, workflow will auto trigger next one.

TODO