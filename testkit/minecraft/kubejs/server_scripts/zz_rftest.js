// RF-Optimized test harness (test builds only): scripted flight path with measurement markers.
// [seconds after join, command, marker]. spreadplayers drops the (spectator) player on the surface;
// the tp then lifts the camera 2 blocks and tilts it 25 degrees down so screenshots show terrain.
var RFTEST_PLAN = [
  [0, 'gamemode spectator @a', 'joined'],
  [2, 'spreadplayers 0 0 0 64 false @a', null],
  [4, 'tp @a ~ ~2 ~ 0 25', null],
  [60, null, 'spawn'],
  [75, 'spreadplayers 3000 3000 0 64 false @a', null],
  [77, 'tp @a ~ ~2 ~ 90 25', null],
  [135, null, 'travel1'],
  [150, 'spreadplayers -3000 -3000 0 64 false @a', null],
  [152, 'tp @a ~ ~2 ~ 180 25', null],
  [210, null, 'travel2'],
  [225, 'spreadplayers 0 0 0 64 false @a', null],
  [227, 'tp @a ~ ~2 ~ 270 25', null],
  [285, null, 'return'],
  [300, null, 'done'],
]
var rftestStart = 0
var rftestStep = 0
var rftestFailed = false

ServerEvents.tick(event => {
  if (rftestFailed) return
  try {
    // This script only ships in client test instances, so the server is always the integrated one.
    var server = event.server
    if (server.getPlayerList().getPlayerCount() == 0) return
    var now = Date.now()
    if (rftestStart == 0) rftestStart = now
    while (rftestStep < RFTEST_PLAN.length && (now - rftestStart) / 1000 >= RFTEST_PLAN[rftestStep][0]) {
      var step = RFTEST_PLAN[rftestStep++]
      if (step[1]) server.runCommandSilent(step[1])
      if (step[2]) console.info('RFTEST mark ' + step[2] + ' mspt=' + Number(server.getAverageTickTime()).toFixed(1))
    }
  } catch (e) {
    rftestFailed = true
    console.error('RFTEST error ' + e)
  }
})
