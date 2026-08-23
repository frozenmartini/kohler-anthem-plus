<p align="center">
  <img src="https://raw.githubusercontent.com/frozenmartini/kohler-anthem-plus/main/docs/images/anthem-system-dark.png" width="300" alt="A Kohler digital valve feeding a rainhead, a body-spray panel and a handshower">
</p>

<h1 align="center">Kohler Anthem Plus</h1>

<p align="center">
  Home Assistant integration for <b>Kohler Digital Anthem</b> and <b>Anthem+</b> shower systems.
</p>

<p align="center">
  <a href="#install"><img src="https://img.shields.io/badge/HACS-custom-41BDF5" alt="HACS: custom repository"></a>
  <img src="https://img.shields.io/badge/Home%20Assistant-2024.2%2B-41BDF5" alt="Home Assistant 2024.2 or later">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT licence">
</p>

<p align="center">
  <sub>Unofficial. Not affiliated with or endorsed by Kohler.</sub>
</p>

---

Kohler sells two products under the Anthem name, and an account can have either or both. They
speak different protocols, so they arrive in Home Assistant as **two devices** — and if you own
both, you get both.

<table>
<tr>
<th width="50%">Anthem<br><sub>THE VALVE CARD</sub></th>
<th width="50%">Anthem Plus<br><sub>THE CONTROLLER CARD</sub></th>
</tr>

<tr>
<td align="center" width="50%"><sub>IN THE KONNECT APP</sub><br><br>
<img src="https://raw.githubusercontent.com/frozenmartini/kohler-anthem-plus/main/docs/images/konnect-anthem.png" width="140" alt="The Konnect app's Anthem screen">
</td>
<td align="center" width="50%"><sub>IN THE KONNECT APP</sub><br><br>
<img src="https://raw.githubusercontent.com/frozenmartini/kohler-anthem-plus/main/docs/images/konnect-anthem-plus.png" width="140" alt="The Konnect app's Anthem Plus screen">
</td>
</tr>

<tr>
<td align="center" width="50%"><sub>IN HOME ASSISTANT</sub><br><br>
<img src="https://raw.githubusercontent.com/frozenmartini/kohler-anthem-plus/main/docs/images/ha-anthem-valve-dark.png" width="140" alt="The Anthem valve card in Home Assistant">
</td>
<td align="center" width="50%"><sub>IN HOME ASSISTANT</sub><br><br>
<img src="https://raw.githubusercontent.com/frozenmartini/kohler-anthem-plus/main/docs/images/ha-anthem-plus-dark.png" width="140" alt="The Anthem Plus card in Home Assistant">
</td>
</tr>

<tr>
<td valign="top" width="50%">
<sub>HIGHLIGHTS</sub>
<ul>
<li><b>Per-outlet control</b> — every outlet is its own switch, in both zones.</li>
<li><b>Custom outlet service</b> — a service call that sets any outlet, temperature and flow
combination the dropdowns can't reach.</li>
<li><b>Endless Shower</b> — the hardware will not run a shower past <b>60 minutes</b>, its longest
allowed setting. This reopens the zone the moment the valve closes it, same outlets, same
temperature.</li>
<li><b>Live outlet and temperature</b> — move a setpoint or flip an outlet and the water follows
immediately. No scene to apply, no confirm step.</li>
<li><b>Warm-up modes</b> — pre-heat before you step in, put back if something disables it.</li>
</ul>
</td>
<td valign="top" width="50%">
<sub>HIGHLIGHTS</sub>
<ul>
<li><b>Per-outlet and temperature sensors</b> — what the controller sees, outlet by outlet.</li>
<li><b>Start the default shower</b> — one switch, no scene to pick first.</li>
<li><b>Stop everything at once</b> — one switch ends the shower, music, steam and light together.
The touchscreen makes you stop each of them separately.</li>
<li><b>Music, steam and light</b> — each reported as its own sensor.</li>
</ul>
</td>
</tr>

<tr>
<td align="center" width="50%"><sub>HARDWARE</sub><br><br>
<img src="https://raw.githubusercontent.com/frozenmartini/kohler-anthem-plus/main/docs/images/hw-valve.svg" width="56" alt="Digital valve"><br>
<sub><b>Digital Valve</b></sub><br><br>
+<br><br>
<img src="https://raw.githubusercontent.com/frozenmartini/kohler-anthem-plus/main/docs/images/hw-interface.svg" width="90" alt="Anthem interface"><br>
<sub><b>Anthem Interface</b><br>K-28214</sub>
</td>
<td align="center" width="50%"><sub>HARDWARE</sub><br><br>
<img src="https://raw.githubusercontent.com/frozenmartini/kohler-anthem-plus/main/docs/images/hw-valve.svg" width="56" alt="Digital valve"><br>
<sub><b>Digital Valve</b></sub><br><br>
+<br><br>
<img src="https://raw.githubusercontent.com/frozenmartini/kohler-anthem-plus/main/docs/images/hw-controller.svg" width="82" alt="Anthem Plus system controller"><br>
<sub><b>System Controller</b><br>K-27756</sub><br><br>
+<br><br>
<img src="https://raw.githubusercontent.com/frozenmartini/kohler-anthem-plus/main/docs/images/hw-interface-plus.svg" width="82" alt="Anthem Plus interface"><br>
<sub><b>Anthem+ Interface</b><br>K-28214-ASC</sub>
</td>
</tr>

<tr>
<td colspan="2" align="center">
<sub>BOTH AT ONCE — ONE VALVE, TWO INTERFACES</sub>
<br><br>
<img src="https://raw.githubusercontent.com/frozenmartini/kohler-anthem-plus/main/docs/images/hw-valve.svg" width="52" alt="Digital valve">
+
<img src="https://raw.githubusercontent.com/frozenmartini/kohler-anthem-plus/main/docs/images/hw-interface.svg" width="78" alt="Anthem interface">
+
<img src="https://raw.githubusercontent.com/frozenmartini/kohler-anthem-plus/main/docs/images/hw-controller.svg" width="78" alt="Anthem Plus system controller">
+
<img src="https://raw.githubusercontent.com/frozenmartini/kohler-anthem-plus/main/docs/images/hw-interface-plus.svg" width="78" alt="Anthem Plus interface">
<br>
<sub><b>Digital Valve</b> + <b>Anthem Interface</b> + <b>System Controller</b> + <b>Anthem+ Interface</b></sub>
<br><br>
A digital valve has <b>two interface ports</b>, so the Anthem interface and the system controller
can be wired to the same valve at the same time. Home Assistant then shows <b>both cards</b> — the
valve and the controller — as two devices.
</td>
</tr>

<tr>
<td colspan="2">

<h2 id="real-time-state">Real-time state</h2>

<p>Kohler's cloud pushes every change over Azure IoT Hub MQTT, and the integration simply listens
— there is <b>no polling loop at all</b>. REST is read twice: once at setup, and again on every
reconnect, because the broker replays nothing when you join.</p>

<ul>
<li><b>Seconds, not intervals.</b> A poller has to choose between stale state and hammering
someone else's cloud. Push has no interval — a change at the touchscreen, in the Konnect app, or
by the valve itself is here as it happens.</li>
<li><b>Every transition, not just the endpoints.</b> Short-lived states slip between polls: a
pause that resolves after about two minutes, a run-time cutoff and the restore right behind it.
Push carries each one.</li>
<li><b>Automations fire on the event.</b> Not on the next scheduled check, and never an interval
late.</li>
<li><b>No token churn.</b> Nothing refreshing credentials on a timer against an identity provider
that rotates its refresh token on every use.</li>
</ul>

</td>
</tr>

<tr>
<td colspan="2">

<h2 id="automation-examples">Automation examples</h2>

<ul>
<li><b>Start the shower from the wall.</b> Bind it to a scene controller by the door — no phone,
no touchscreen.</li>
<li><b>Clear the steam afterwards.</b> Run the exhaust fan for 30 minutes after the water stops,
then shut it off.</li>
<li><b>Music on the same switch.</b> One press starts the shower and the playlist together.</li>
<li><b>One command ends everything.</b> Shower, music, steam and light, in a single action.</li>
<li><b>Dim the lights when it is ready.</b> The moment the water reaches temperature, drop the
bathroom lights to where you want them.</li>
<li><b>Fill the tub on the way home.</b> Fifteen minutes of tub filler, timed to when you actually
arrive.</li>
</ul>

</td>
</tr>

<tr>
<td colspan="2">

<h2 id="requirements">Requirements</h2>

<ul>
<li>Home Assistant <b>2024.2</b> or later</li>
<li>A Kohler Konnect account, with the shower already set up in the Konnect app</li>
<li><b>Internet access.</b> Control is cloud-only for both products. If Kohler's cloud is
unreachable, nothing here can turn the shower on or off.</li>
</ul>

<p>The only Python dependency is <code>paho-mqtt</code>, installed automatically.</p>

</td>
</tr>

<tr>
<td colspan="2">

<h2 id="install">Install</h2>

<p>This integration is <b>not in HACS's default store.</b> Add it as a custom repository.</p>

<b>Via HACS</b>
<ol>
<li>In HACS, open the ⋮ menu and choose <b>Custom repositories</b></li>
<li>Add <code>frozenmartini/kohler-anthem-plus</code> (or the full GitHub URL), category
<b>Integration</b></li>
<li>Find <b>Kohler Anthem Plus</b> in HACS and install it</li>
<li>Restart Home Assistant</li>
</ol>
<p>HACS installs from <b>releases</b>, not from the latest commit.</p>

<b>Manually</b>
<p>This repository <b>is</b> the integration — <code>manifest.json</code> sits at its root. Copy
its contents into <code>custom_components/kohler_anthem_plus/</code> in your Home Assistant
configuration directory (the folder name must be exactly <code>kohler_anthem_plus</code>) and
restart.</p>

</td>
</tr>

<tr>
<td colspan="2">

<h2 id="setup">Setup</h2>

<p><b>Settings → Devices &amp; Services → Add Integration → Kohler Anthem Plus</b></p>

<p>Sign in with your Konnect account and you are done. The integration reads the account, works
out which hardware you have — valve model, how the outlets split across zones, whether a
controller is in front of it — and builds the matching devices itself. Your password is exchanged
for a token and never stored, and temperature units follow whatever your Konnect account already
uses.</p>

<p>There is no Configure dialog. Every setting that can change after setup is an entity on the
device page, where automations and dashboards can reach it too.</p>

</td>
</tr>

<tr>
<td colspan="2">

<h2 id="hardware">What works, and what does not</h2>

<b>Supported</b>
<ul>
<li><b>Kohler Anthem Digital Valve</b> — <code>K-28209</code>, <code>K-28210</code>,
<code>K-28211</code>, <code>K-28212</code>. One unit containing up to two zones, each with up to
three outlets. An installation that doesn't match one of the four still works — an unrecognised
outlet split produces a usable model rather than an error.</li>
<li><b>Anthem Interface</b> (<code>K-28214</code>) and <b>Anthem+ Interface</b>
(<code>K-28214-ASC</code>), with the <b>Anthem+ System Controller</b> (<code>K-27756</code>).</li>
</ul>

<b>Not supported</b>
<ul>
<li><b>The older DTV systems.</b> A previous generation of Kohler digital showering, on a
different protocol entirely. Nothing here applies to them.</li>
<li><b>Kohler Duo Control.</b> No Wi-Fi and no Konnect connection, so there is nothing for an
integration to talk to.</li>
<li>⚠️ <b>The mechanical Anthem.</b> Kohler sells both under that name. Only the digital,
network-connected one has an API.</li>
</ul>

</td>
</tr>

<tr>
<td colspan="2">

<h2 id="contributing">Contributing</h2>

<p>Different hardware is the most useful thing anyone can contribute. Two things make a report
diagnosable:</p>

<ul>
<li><b>Download diagnostics</b> — on the integration card and both device pages. One JSON report
of the whole installation, with credentials, account identity and serial numbers redacted. On
anything other than a K-28212, this is the single most useful file you can send.</li>
<li><b>Report Log</b> — a switch on both device pages that captures every raw MQTT message, one
file per switch-on, continuing across a Home Assistant restart so "it breaks when I restart" stays
one piece of evidence.</li>
</ul>

<p><b>Check both before sharing</b> — they carry device identifiers and show when the shower was
used. The reports folder lives inside the integration, so updating or reinstalling deletes it.</p>

</td>
</tr>

<tr>
<td colspan="2">

<h2 id="known-limitations">Known limitations</h2>

<ul>
<li><b>Cloud-only.</b> No local control path exists for either product.</li>
<li><b>No flow control.</b> Both interfaces overwrite the flow limits with their own
calibration, so a flow setting cannot be held accurately — not by this integration, and not by
the Konnect app either.</li>
<li><b>The API is undocumented</b> and Kohler can change it without notice.</li>
<li><b>One installation tested.</b> A single K-28212 — six outlets, three and three — with a
controller on firmware 2.88. Other models are supported on what the protocol says, not on anyone
having run them.</li>
</ul>

<p>This is an unofficial, community-built integration, reverse-engineered from Kohler's cloud
protocol. It is not a supported product, and it comes with no warranty of any kind. Anything that
can run water deserves that caution.</p>

</td>
</tr>

<tr>
<td colspan="2">

<h2 id="documentation">Documentation</h2>

<p><b><a href="https://github.com/frozenmartini/kohler-anthem-plus/blob/main/docs/user_guide.md">The full guide</a></b> covers every entity, the
<code>send_valve_hex</code> service, each feature in detail, automation examples and
troubleshooting.</p>

<p><b><a href="https://github.com/frozenmartini/kohler-anthem-plus/tree/main/docs">docs/</a></b> is a complete protocol reference, not just integration notes —
the valve command word byte by byte, both REST APIs, the MQTT message catalogue, and case studies
that work real showers through message by message. Start with
<a href="https://github.com/frozenmartini/kohler-anthem-plus/blob/main/docs/architecture.md">docs/architecture.md</a> for the two-device model.</p>

</td>
</tr>

<tr>
<td colspan="2">

<h2 id="prior-art">Prior art</h2>

<p><a href="https://github.com/frozenmartini/kohler-anthem-plus/blob/main/docs/prior_art.md">docs/prior_art.md</a> credits the two projects this one started
from — <a href="https://github.com/kenyonj/kohler-konnect-ha">kohler-konnect-ha</a> and
<a href="https://github.com/yon/kohler-anthem">kohler-anthem</a> — and records where their
readings differ from what the wire actually does.</p>

</td>
</tr>

<tr>
<td colspan="2">

<h2 id="licence-and-trademarks">Licence and trademarks</h2>

<p>MIT — see <a href="https://github.com/frozenmartini/kohler-anthem-plus/blob/main/LICENSE">LICENSE</a>.</p>

<p>Kohler, Anthem, Anthem+ and Konnect are trademarks of Kohler Co. This project is not affiliated
with, authorised by, or endorsed by Kohler Co., and is not a supported product.</p>

</td>
</tr>
</table>
