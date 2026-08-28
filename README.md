<center>

<p align="center">
<img src="https://raw.githubusercontent.com/frozenmartini/kohler-anthem-plus/main/docs/images/banner-mark.svg" width="150" alt="Kohler Anthem Plus">
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

</center>


<table cellpadding="6">
<tr>
<th width="49%"><h3>Anthem</h3><sub>THE VALVE CARD</sub></th>
<th width="2%" align="center"><img src="https://raw.githubusercontent.com/frozenmartini/kohler-anthem-plus/main/docs/images/vline-grey-70.svg" width="1" height="70" alt=""></th>
<th width="49%"><h3>Anthem Plus</h3><sub>THE CONTROLLER CARD</sub></th>
</tr>

<tr>
<td align="center" width="49%"><sub>IN THE KONNECT APP</sub><br><br>
<img src="https://raw.githubusercontent.com/frozenmartini/kohler-anthem-plus/main/docs/images/konnect-anthem.png" width="300" alt="The Konnect app's Anthem screen">
</td>
<td width="2%" align="center"><img src="https://raw.githubusercontent.com/frozenmartini/kohler-anthem-plus/main/docs/images/vline-grey-465.svg" width="1" height="465" alt=""></td>
<td align="center" width="49%"><sub>IN THE KONNECT APP</sub><br><br>
<img src="https://raw.githubusercontent.com/frozenmartini/kohler-anthem-plus/main/docs/images/konnect-anthem-plus.png" width="300" alt="The Konnect app's Anthem Plus screen">
</td>
</tr>

<tr>
<td align="center" width="49%"><sub>IN HOME ASSISTANT</sub><br><br>
<img src="https://raw.githubusercontent.com/frozenmartini/kohler-anthem-plus/main/docs/images/ha-anthem-valve-dark.png" width="300" alt="The Anthem valve card in Home Assistant">
</td>
<td width="2%" align="center"><img src="https://raw.githubusercontent.com/frozenmartini/kohler-anthem-plus/main/docs/images/vline-grey-428.svg" width="1" height="428" alt=""></td>
<td align="center" width="49%"><sub>IN HOME ASSISTANT</sub><br><br>
<img src="https://raw.githubusercontent.com/frozenmartini/kohler-anthem-plus/main/docs/images/ha-anthem-plus-dark.png" width="300" alt="The Anthem Plus card in Home Assistant">
</td>
</tr>

<tr>
<td valign="top" width="49%">
<b>HIGHLIGHTS</b><br><br>
<b>Per-outlet control</b> — every outlet is its own switch, in both zones.
<br><br>
<b>Endless Shower</b> — your shower is no longer capped at <b>60 minutes</b>. The moment the valve
shuts off, it goes back on automatically — same outlets, same temperature.
<br><br>
<b>Live outlet and temperature</b> — move a setpoint or flip an outlet and the water follows
immediately. No scene to apply, no confirm step.
</td>
<td width="2%" align="center"><img src="https://raw.githubusercontent.com/frozenmartini/kohler-anthem-plus/main/docs/images/vline-grey-340.svg" width="1" height="340" alt=""></td>
<td valign="top" width="49%">
<b>HIGHLIGHTS</b><br><br>
<b>Per-outlet and temperature sensors</b> — what the controller sees, outlet by outlet.
<br><br>
<b>Start the default shower</b> — one switch, no scene to pick first.
<br><br>
<b>Stop everything at once</b> — one switch ends the shower, music, steam and light together. The
touchscreen makes you stop each of them separately.
<br><br>
<b>Music, steam and light</b> — each reported as its own sensor. Music needs Kohler's
K-30319 amplifier; it is not built into the controller.
</td>
</tr>

<tr>
<td align="center" width="49%"><b>HARDWARE</b><br><br>
<img src="https://raw.githubusercontent.com/frozenmartini/kohler-anthem-plus/main/docs/images/hw-valve.svg" width="84" alt="Digital valve"><br>
<sub><b>Digital Valve</b></sub><br>
+<br>
<img src="https://raw.githubusercontent.com/frozenmartini/kohler-anthem-plus/main/docs/images/hw-interface.svg" width="135" alt="Anthem interface"><br>
<sub><b>Anthem Interface</b><br>K-28214</sub>
</td>
<td width="2%" align="center"><img src="https://raw.githubusercontent.com/frozenmartini/kohler-anthem-plus/main/docs/images/vline-grey-324.svg" width="1" height="324" alt=""></td>
<td align="center" width="49%"><b>HARDWARE</b><br><br>
<img src="https://raw.githubusercontent.com/frozenmartini/kohler-anthem-plus/main/docs/images/hw-valve.svg" width="84" alt="Digital valve"><br>
<sub><b>Digital Valve</b></sub><br>
+<br>
<img src="https://raw.githubusercontent.com/frozenmartini/kohler-anthem-plus/main/docs/images/hw-controller.svg" width="123" alt="Anthem Plus system controller"><br>
<sub><b>System Controller</b><br>K-27756</sub><br>
+<br>
<img src="https://raw.githubusercontent.com/frozenmartini/kohler-anthem-plus/main/docs/images/hw-interface-plus.svg" width="123" alt="Anthem Plus interface"><br>
<sub><b>Anthem Plus Interface</b><br>K-28214-ASC</sub>
</td>
</tr>
<tr>
<td colspan="3">

<hr>

<center><p align="center">
<b>BOTH AT ONCE, 2 SYSTEMS COMBINED</b>
<br><br>
<img src="https://raw.githubusercontent.com/frozenmartini/kohler-anthem-plus/main/docs/images/hw-combo.svg" width="483" alt="Anthem Plus interface plus system controller plus Anthem interface">
<br>
<sub><b>Anthem Plus System</b>&emsp;+&emsp;<b>Anthem Interface</b></sub>
<br><br>
Plug the <b>System Controller</b> into a valve port and add an <b>Anthem Interface (K-28214)</b>
into the other, and the Anthem Plus system gains full Anthem shower control alongside everything it
already does. The two stay in step — start at either panel and the other follows — and Home
Assistant shows <b>both cards</b>, valve and controller, as two devices working in tandem.
<br><br>
<b><a href="https://github.com/frozenmartini/kohler-anthem-plus/blob/main/docs/user_guide.md#using-both-together">How the combined system works →</a></b>
</p></center>

<hr>

</td>
</tr>

<tr>
<td colspan="3">

<h3 id="real-time-state">MQTT real-time state</h3>

<p>Kohler's cloud tells Home Assistant the moment anything changes, and this integration simply
listens. Nothing here needlessly checks the shower's state every 10 seconds.</p>

<ul>
<li><b>It is live.</b> Open an outlet at the touchscreen, nudge the temperature in the Konnect app,
or let the shower stop itself — Home Assistant knows as it happens, not on the next check.</li>
<li><b>Nothing slips past.</b> A shower is full of brief moments: a pause, a shut-off, the restart
right behind it. Each one arrives instantly, with no changes lost between checking intervals.</li>
<li><b>Automations fire on the moment.</b> The trigger is the event itself, so nothing runs a
minute late.</li>
<li><b>Easy on your network — and on Kohler's.</b> No constant asking, no signing in over and over.
The connection stays open and waits.</li>
</ul>

<hr>

<h3 id="automation-examples">Automation examples</h3>

<ul>
<li><b>Start the shower from the wall.</b> Bind it to a scene controller by the door — no phone,
no touchscreen.</li>
<li><b>Clear the steam afterwards.</b> Run the exhaust fan for 30 minutes after the water stops,
then shut it off.</li>
<li><b>Music on the same switch.</b> One press starts the shower and the playlist together —
on a system fitted with Kohler's K-30319 amplifier.</li>
<li><b>One switch ends everything.</b> No more turning off the shower, then the music, then the
steam, then the light — one command stops all of it.</li>
<li><b>Dim the lights when the water is ready.</b> The moment it reaches temperature, drop the
bathroom lights to where you want them.</li>
<li><b>Fill the tub on the way home.</b> Fifteen minutes of tub filler, timed to when you actually
arrive.</li>
</ul>

<hr>

<h3 id="requirements">Requirements</h3>

<ul>
<li>Home Assistant <b>2024.2</b> or later</li>
<li>A Kohler Konnect account, with the shower already set up in the Konnect app</li>
<li><b>Internet access.</b> Control is cloud-only for both products. If Kohler's cloud is
unreachable, nothing here can turn the shower on or off.</li>
</ul>

<p>The only Python dependency is <code>paho-mqtt</code>, installed automatically.</p>

<hr>

<h3 id="install">Install</h3>

<p>This integration is <b>not in HACS's default store.</b> Add it as a custom repository.</p>

<b>Via HACS</b>
<p><a href="https://my.home-assistant.io/redirect/hacs_repository/?owner=frozenmartini&amp;repository=kohler-anthem-plus&amp;category=integration"><img src="https://my.home-assistant.io/badges/hacs_repository.svg" alt="Open this repository in HACS on your Home Assistant"></a></p>
<p>That button opens this repository in HACS on your own instance, adds it as a custom repository
and offers the download. It needs <a href="https://my.home-assistant.io/">My Home Assistant</a>
set up in your browser. Otherwise, add it by hand:</p>
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

<hr>

<h3 id="setup">Setup</h3>

<p><b>Settings → Devices &amp; Services → Add Integration → Kohler Anthem Plus</b></p>

<p>Sign in with your Konnect account and you are done. The integration reads the account, works
out which hardware you have — valve model, how the outlets split across zones, whether a
controller is in front of it — and builds the matching devices itself. Your password is exchanged
for a token and never stored, and temperature units follow whatever your Konnect account already
uses.</p>

<p>There is no Configure dialog. Every setting that can change after setup is an entity on the
device page, where automations and dashboards can reach it too.</p>

<hr>

<h3 id="hardware">What works, and what does not</h3>

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

<hr>

<h3 id="contributing">Contributing</h3>

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

<hr>

<h3 id="known-limitations">Known limitations</h3>

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

<hr>

<h3 id="documentation">Documentation</h3>

<p><b><a href="https://github.com/frozenmartini/kohler-anthem-plus/blob/main/docs/user_guide.md">The full guide</a></b> covers every entity, the
<code>send_valve_hex</code> service, each feature in detail, automation examples and
troubleshooting.</p>

<p><b><a href="https://github.com/frozenmartini/kohler-anthem-plus/tree/main/docs">docs/</a></b> is a complete protocol reference, not just integration notes —
the valve command word byte by byte, both REST APIs, the MQTT message catalogue, and case studies
that work real showers through message by message. Start with
<a href="https://github.com/frozenmartini/kohler-anthem-plus/blob/main/docs/architecture.md">docs/architecture.md</a> for the two-device model.</p>

<hr>

<h3 id="prior-art">Prior art</h3>

<p><a href="https://github.com/frozenmartini/kohler-anthem-plus/blob/main/docs/prior_art.md">docs/prior_art.md</a> credits the two projects this one started
from — <a href="https://github.com/kenyonj/kohler-konnect-ha">kohler-konnect-ha</a> and
<a href="https://github.com/yon/kohler-anthem">kohler-anthem</a> — and records where their
readings differ from what the wire actually does.</p>

<hr>

<h3 id="licence-and-trademarks">Licence and trademarks</h3>

<p>MIT — see <a href="https://github.com/frozenmartini/kohler-anthem-plus/blob/main/LICENSE">LICENSE</a>.</p>

<p>Kohler, Anthem, Anthem+ and Konnect are trademarks of Kohler Co. This project is not affiliated
with, authorised by, or endorsed by Kohler Co., and is not a supported product.</p>

</td>
</tr>
</table>
