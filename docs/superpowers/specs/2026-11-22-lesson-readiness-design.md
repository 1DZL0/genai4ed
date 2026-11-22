# Lesson readiness: devices, live health, quick fixes

Date: 22 November 2026. Diesel said yes to the three parts on 22 Nov ("yes i think we should do
that"). The two open choices were left to my picks: switch to a backup model by hand, and no
phone alert yet. After a review, Diesel decided on 22 Nov: no deploy for Athens; the
real-device check uses a test class that the study data leaves out; nothing committed yet. He
is not sure who will be at the Mac during lessons, so the design works either way.

## Why

PACT is about to be shown in Athens (from 23 Nov) and then used in real lessons. Two things
can spoil a lesson: a device that cannot run the site, and a failure in the middle of a lesson
that nobody notices until students complain. Diesel wants to test on the devices schools
actually have, see straight away when something breaks during a lesson, and have quick fixes
ready.

## What exists today

The design builds on these facts, checked in the code on 22 Nov.

- **Browser floor.** Next.js 16 supports Chrome and Edge 111+, Safari 16.4+ and Firefox 111+.
  Tailwind 4, which draws every page, needs Chrome 111, Safari 16.4 and Firefox 128
  (tailwindcss.com/docs/compatibility). So the real floor is Chrome or Edge 111, Safari 16.4
  (iOS and iPadOS 16.4) and Firefox 128, all from 2023 or 2024. Below it the page breaks with
  no explanation.
- **Pages ask the server every 8 to 15 seconds.** There is no live connection, which school
  networks handle well.
- **Every tutor reply is stored** as an `AgentTurn` with its model, `latency_ms` and outcome. A
  failed reply is stored too: `latency_ms` 0, `conflicts` `["malformed_output"]`, and the error
  text under `response.error`. Its `request` holds the student's words. The student sees "The
  agent couldn't answer just now. Try sending that again." and keeps what they typed.
- **The server already logs** one line for each failed (500-level) or slow request: method,
  path, status, milliseconds (`log_failures` in `backend/app/main.py`). Nothing reads these
  during a lesson.
- **The model** is the `OPENROUTER_MODEL` line in `.env`, which docker-compose passes to the
  api container. Changing it needs a restart of that container, not a rebuild. Calls time out
  after 60 s. There is no backup model.
- **A daily cap** of 200 tutor turns per student (`student_turns_per_day`). Past it the student
  sees "You've done a lot today. Ask your teacher before carrying on."
- **The teacher can** pause the class, print the lesson card, and give one student a fresh
  join code from the Classes page (which ends that student's old sign-ins).
- **The live site runs on this Mac**, a MacBook Pro (on 22 Nov it was serving on battery):
  four containers (db, api, web, backup) and the Cloudflare tunnel connector, which runs as a
  system service (`/Library/LaunchDaemons/com.cloudflare.cloudflared.plist`). If the Mac sleeps
  or loses internet, the site is down for everyone. Restarting the connector needs Diesel's
  password: `sudo launchctl kickstart -k system/com.cloudflare.cloudflared`, back in under 20
  seconds.
- **The tunnel can fail while looking alive.** On 16 Nov, after a network change, the connector
  dropped all its connections and stopped retrying while its process stayed up, and the public
  address gave Cloudflare error 1033. Its own check, `127.0.0.1:20241/ready`, showed 0 ready
  connections.
- **On this Mac, 127.0.0.1:8000 is the Pharos portal**, so `localhost:8000` does not reach
  PACT's API. The API is reached from inside its container (as its healthcheck does) or through
  the website.
- **The scripted demo agent** answers when `AGENT_CLIENT` is neither `openrouter` nor `auto`
  with a key: free and predictable.
- **The research key** (`X-Research-Key`) is the existing researcher-only lock; without it the
  research endpoints answer 404.

## Goals

1. **Device check.** A repeatable run that opens the main pages on the engines behind Safari,
   Chrome and Firefox, at iPad, iPhone, Android phone, Chromebook and laptop sizes, and says
   what broke, with screenshots.
2. **Too-old notice.** A browser below the floor shows a plain message instead of a broken page.
3. **Real-device check.** Ten minutes on one real iPad and one Chromebook, on the school's
   network, before the first lesson at a school.
4. **Lesson health page.** One page for Diesel, on a laptop or a phone: are the server, the
   database and the model fine, and for each running lesson, how many students are active,
   whether replies fail and how slow they are. A failing model shows within 20 seconds of the
   first failed reply, and one that hangs within about 40 seconds.
5. **Status command.** One command on the Mac that says what is up and what is not.
6. **"If it breaks" sheet.** One page, each symptom with a fix that takes about a minute,
   including a one-command switch to the backup model.
7. **Test runs stay out of the study data.** Checks on the live site never reach the research
   view or the export.

## Non-goals

- No automatic switch to a backup model (Diesel's pick: by hand).
- No phone alerts yet.
- No outside services: no Sentry, no BrowserStack, no push service. Student words could leak
  into error reports, outside services need the data protection officer, and they cost money.
- No support for browsers below the floor: we tell people, we do not fix it.
- No failure view for teachers.
- No change to what students see when a reply fails.
- No full-class load test. That is a separate piece, recommended before the first real class.
- No Greek text.

## Anti-goals

Any of these makes it a failure even if it works.

- Students' words on the health page, in a log line, or in anything the device check saves.
- A script or page that prints a secret: an `.env` value, the research key, the site password,
  the tunnel token. The one exception is the model's name, which the research page already
  shows.
- The device check spending money, touching the live site or its database, or breaking the
  other local previews.
- A health page that shows green while replies are failing.

## Approaches considered

**Device testing.**

- A. Automated runs on the three browser engines, the too-old notice, and a short check on
  real devices. **Picked:** free, repeatable, and the notice covers what the engines cannot.
- B. A paid device cloud (BrowserStack) with real old iPads and Chromebooks. Costs money and
  sends the site to an outside company. Kept for later, only if A misses real problems.
- C. Only borrowed real devices. Slow, not repeatable, and depends on what is at hand.

**Monitoring.**

- A. A researcher-only health page fed by records PACT already keeps, plus a status command.
  **Picked:** nothing new leaves the server and almost nothing new is recorded.
- B. An outside error service (Sentry, Grafana Cloud). Student words could reach its reports,
  it needs the data protection officer, and it is more to set up.
- C. Reading the server logs. Needs a terminal on the Mac, and says nothing about the model's
  credit or which lesson is hurting.

**When the model fails.**

- A. Switch by hand with one command. **Picked:** Diesel decides, and knows from what time the
  replies came from the backup.
- B. Automatic fallback (OpenRouter can take a list of models). The lesson carries on, but
  replies silently come from another model, which mixes the research data.

## The design

### Part 1: Device check

- A script, `scripts/device-check`, drives Playwright (Python, pinned at 1.64.1 through uv, as
  in earlier checks) on WebKit, Chromium and Firefox. The three browsers download once.
- It runs against a production build of the current code with its own backend on the scripted
  agent and its own scratch database, which the check creates and migrates. It uses only test
  accounts named `test-device-...`, makes no model calls, and touches neither the live database
  nor the test copy.
- Devices: iPad portrait and landscape (WebKit), iPhone (WebKit), Android phone (Chromium),
  Chromebook at 1366 by 768 (Chromium), and laptops at 1440 by 900 (WebKit) and 1280 by 800
  (Firefox).
- Steps: the home page; joining with a code; the student's lesson page (send a message, see the
  reply, press "Ask my teacher"); teacher sign-in; the teacher's class board showing that
  student and the alert; the lessons list; the research key form (only that it loads).
- On every page: no script errors in the console, no failed requests other than expected ones,
  no sideways scroll, the main button on screen and at least 40 px tall on phones and tablets,
  and a screenshot.
- Output: one pass or fail line per page per device, and a contact sheet of every screenshot
  as a plain HTML file in Downloads for Diesel to look through.
- It can also run read-only against the live address, on the pages that need no sign-in (the
  password page, then home and join, with the site password read from `.env` and never
  printed), so we know how the site Athens sees looks on each engine. Pages behind sign-in are
  checked on the local build only. My call.
- It also checks the notice from Part 2: a run where the browser is made to fail the feature
  test must show the notice.
- What it cannot do: Playwright's engines are the newest versions, so it proves the layout and
  the steps at these sizes, not old versions. Part 2 and Part 3 cover old devices.

### Part 2: Too-old notice

- A small script in the page head, run before the app's own code, tests features rather than
  the browser's name, matching the floor (Chrome or Edge 111, Safari 16.4, Firefox 128).
- A browser that fails sees only this, styled without the app's stylesheet:
  "This browser is too old for PACT. Please update it, or use another device. PACT works on
  Safari 16.4 or newer (on iPad and iPhone, iOS 16.4 or newer), Chrome or Edge 111 or newer
  (Chromebooks included), and Firefox 128 or newer."
- A browser that passes sees no change.

### Part 3: Real-device check

Ten minutes, on one real iPad and one Chromebook (or whatever the school uses), on the school's
own Wi-Fi, signed in as a student of the standing test class (Part 7). It is a checklist in the
sheet (Part 6):

- open the address; if the school's filter blocks it, ask the school's IT to allow it;
- check the iPad's version (Settings, General, About: 16.4 or newer);
- join as a test student, type a message with the on-screen keyboard, and check the box stays
  in view and the reply arrives;
- turn the iPad sideways and back;
- press "Ask my teacher" and see the alert on the teacher's board;
- print the lesson card.

### Part 4: Lesson health page

- At `/research/health` on the website, opened with the research key. Without the key the
  server answers 404, as the research view does. The page refreshes every 10 seconds and works
  at phone width.
- Three lights at the top:
  - **Server:** green when the last refresh got an answer; red "Can't reach the server" with the
    time of the last good answer.
  - **Database:** the server's own check (`select 1`).
  - **Model:** the model in use and the credit left on the OpenRouter key, from OpenRouter's
    key endpoint (`GET https://openrouter.ai/api/v1/key`, fields `limit` and
    `limit_remaining`), asked at most once a minute. If that check fails the page says "credit:
    can't check" and nothing else breaks. Red when the last 3 tutor calls all failed or less
    than $5 is left; amber when any call failed in the last 10 minutes, a reply took over 30
    seconds, or less than $20 is left; green otherwise.
  - **Calls still waiting** count toward the model light too. A failed call is recorded only
    when it gives up, after the 60-second timeout, so the API also counts tutor calls still
    waiting for the model, per lesson, in its memory (it runs as one process). Any call waiting
    over 30 seconds makes the light amber; 3 or more make it red. My call: 30 seconds matches
    the slow-reply line above and the school-day test's bar for the slowest replies.
- Under the lights: **server errors in the last 10 minutes**, counted in the API's memory by the
  middleware that already logs them (500-level responses other than a failed tutor reply, which
  is counted per lesson). The count starts again when the API restarts.
- Then **one row per running lesson**: a lesson that is open or paused and was opened or used
  in the last 2 hours, so lessons left open for days do not clutter it. Each row shows: lesson
  title, class, paused or not; students active in the last 5 minutes out of those who joined;
  replies and failed replies in the last 10 minutes and since the lesson opened; typical and
  slowest reply time in the last 10 minutes; the last error with its time (the first 120
  characters of the error text). Lessons with failures come first. With none running it says
  "No lesson is running."
- It never shows students' words: the endpoint never reads a turn's `request`. It never shows
  the key.
- The key is kept in that browser tab (`sessionStorage`), so a phone that reloads the tab does
  not ask again mid-lesson; it is gone when the tab closes.
- **Switch buttons**, "Use the backup model" and "Back to the main model", because Diesel may
  have only his phone, and the commonest fix must work from it. Only those two models, both
  named in the server's settings (the main one as now, the backup in a new setting), never a
  free choice. The choice is stored in the database, so the API uses it on its next call with
  no restart and keeps it after one; while the backup is chosen it wins over the `.env` line.
  The page shows which model is in use and since when, and every switch is recorded with its
  time. My call.

### Part 5: Status command and model switch

- `scripts/status`, a bash script like `scripts/check`, prints one line per check, "ok" or the
  problem and its fix, and exits 0 when everything is fine, 1 otherwise:
  - Docker running, and the four containers up (healthy where they have a healthcheck);
  - the API ready with the database answering, asked from inside its container;
  - the public address answering through the tunnel (any answer from the site, including its
    password page, counts), and the connector's own check showing ready connections, since a
    running process is not proof (16 Nov);
  - the model's credit, asked from inside the api container, and the failed replies of the last
    10 minutes, from a read-only count in the database that never reads students' words;
  - the newest backup under 26 hours old, and free disk space;
  - the Mac on mains power and kept awake (`caffeinate` running).
- The status command works on whatever is live, old code included, so it does not rely on the
  new health endpoint. My call: that way it is useful before the next deploy.
- `scripts/switch-model <model id>` is how to switch until the health page's buttons are live,
  and when the site itself is down. It replaces the `OPENROUTER_MODEL` line in `.env`, recreates
  only the api container (`docker compose up -d --no-deps api`), waits until it is healthy, and
  says which model it switched from, so switching back is the same command. A student who sends
  during the restart (about 10 seconds) gets the usual "try again" message. Every reply records
  its model, so the research data shows which replies came from the backup.
- Before it restarts anything, it checks that the api container would come back on the image it
  runs now (on 22 Nov both were the 16 Nov build). If someone has built a newer image since, a
  restart would quietly deploy it, so the command stops and says so.
- The backup model is Sonnet 5.5: same family as the main model, faster and cheaper. It is
  tried once on the test copy before anyone relies on it (a short lesson, under $1), with
  Diesel's word before that spend.

### Part 6: "If it breaks" sheet

`docs/if-it-breaks.md` in the repo, and a one-page printable copy as a plain HTML file in
Downloads. No secrets in it: where a secret is needed it names the line in `.env`.

- **Before a lesson (2 minutes):** plug the Mac in; run `caffeinate -dims` in a Terminal window
  and leave it open; run `scripts/status`; open the health page; the teacher prints the lesson
  card.
- **Then one row per symptom, with the first check and the fix:**
  - Many students get "couldn't answer": look at the model light. Credit low: raise the key's
    limit on OpenRouter. Model failing: `scripts/switch-model` to the backup. Meanwhile the
    teacher pauses the class.
  - Replies very slow (over 30 seconds): the same; switch if it lasts more than 2 minutes.
  - The site will not open for anyone: run `scripts/status` and do what it names: wake or plug
    in the Mac, start the containers (`docker compose up -d`), or restart the tunnel connector
    (`sudo launchctl kickstart -k system/com.cloudflare.cloudflared`, with your password, back in
    under 20 seconds).
  - It opens on some devices but not others: the too-old notice means another device; a blocked
    address means the school's IT.
  - One student cannot get in: the teacher gives that student a new code from the Classes page.
  - One student's tutor says "You've done a lot today": the daily cap. The teacher decides; the
    cap is a setting and a restart.
  - The teacher's board stops changing: reload the page.
  - Everything is down: pause the class if possible and carry on from the printed card.
- **After:** note the time, what happened and the fix, so the research record can account for it.

### Part 7: The test class and the study data

Diesel's decision (22 Nov).

- One standing test teacher on the live site, `test-device-check`, with its own class and a
  short lesson, made once with Diesel's word when the first real-device check comes up. Every
  real-device check signs in as a student of that class.
- The research view and the research export leave out lessons taught by accounts whose username
  starts with `test-`, so test runs never reach the study data. The health page still shows
  them, marked as tests.
- Before the deploy that brings this, Diesel gets a read-only list of the live accounts named
  `test-...`, so he sees what will leave the research view.

## Left to the builder

- The exact feature tests for the notice, as long as they land on the floor above.
- How the device check sets up its class, lesson and student (through the API or straight into
  its scratch database), the exact device profiles, and the contact sheet's layout.
- Where the device check's build goes: other previews serve from `frontend/.next`, so it must
  build somewhere else and leave them running.
- The health endpoint's path (under `/api/research/`, behind the research key), its queries and
  its response shape.
- How the status command and the model switch are tested without stopping or restarting any
  live container (see Constraints).
- The thresholds in the light rules may be tuned if they prove noisy; any change is written down.
- Where the model choice is stored and how often the API reads it again (every few seconds at
  most).

## Constraints

- Nothing reaches the live site until the next deploy, which needs Diesel's word. Every live
  step (deploy, the switch script run for real, a live restart) needs his word at that moment.
- No script, page or log prints a secret (see Anti-goals). Nothing here writes to the live
  database except the test class in Part 7 (made with Diesel's word) and a switch pressed on
  the health page.
- Tests and checks use only clearly named test accounts, never teacher-1, teacher-2, teacher-3,
  the professor's, a colleague's or Diesel's own.
- `localhost:8000` on this Mac is the Pharos portal; scripts must not mistake it for PACT.
- All words on pages and in the sheet are plain, with no long dashes.
- New backend code gets tests (the project's floor: no assertions removed, 80% of changed lines
  covered).

## Order of building

Diesel decided there is no deploy for Athens, so what works on today's live site comes first.

1. For Athens, today: the status command, the model switch command, and the sheet with its
   checklist, all working against what is live now.
2. The device check: read-only on the live address's public pages, then the full run on the
   local build of the new code.
3. After Athens, with the next deploy: the too-old notice, the health page with its switch
   buttons, and the test-class filter.

On the deploy that brings these to the live site, everyone signs in again (the new cookies).
Nothing is committed until Diesel says so (22 Nov: not yet).
