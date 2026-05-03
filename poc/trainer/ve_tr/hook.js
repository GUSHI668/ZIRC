// hook.js

// Note: Will crash due to different data structure

var STOLEN_VEHICLE_TEAM_PTR = null;
var SPOOF_ENABLED = false;
var BASE_ADDR = null;

function getModuleBase(name) {
    var mod = Process.findModuleByName(name);
    return mod ? mod.base : null;
}

function getIl2cppClassName(objPtr) {
    if (objPtr.isNull()) return "null";
    try {
        var klassPtr = objPtr.readPointer();
        var classNamePtr = klassPtr.add(0x10).readPointer();
        return classNamePtr.readUtf8String();
    } catch(e) {
        return "Unknown";
    }
}

function initHooks() {
    var gameAssembly = getModuleBase("GameAssembly.dll");
    if (!gameAssembly) return;
    BASE_ADDR = gameAssembly;

    var addr_get_Team = gameAssembly.add(53264624);
    var addr_VehicleTeam_ctor = gameAssembly.add(51317984);

    send({ type: "info", payload: "Attaching Precision Stealer & Call Trace..." });

    // Hook: VehicleTeam
    try {
        Interceptor.attach(addr_VehicleTeam_ctor, {
            onEnter: function(args) {
                var ptr = args[0]; // THIS pointer of VehicleTeam
                if (!ptr.isNull() && getIl2cppClassName(ptr) === "VehicleTeam") {
                    STOLEN_VEHICLE_TEAM_PTR = ptr;
                    send({ type: "hook", payload: "[STEALER] Captured VehicleTeam -> " + ptr });
                }
            }
        });
    } catch(e) {}

    // Hook: Train Target
    try {
        Interceptor.attach(addr_get_Team, {
            onLeave: function(retval) {
                if (!SPOOF_ENABLED) return;

                var originalClassName = getIl2cppClassName(retval);
                send({ type: "hook", payload: "[TargetTrain] get_Team returns -> " + retval + " | Class: " + originalClassName });

                var backtrace = Thread.backtrace(this.context, Backtracer.ACCURATE);
                var traceMsg = "[TRACE] get_Team Called By:\n";
                for (var i = 0; i < backtrace.length; i++) {
                    var addr = backtrace[i];
                    var offset = addr.sub(BASE_ADDR).toInt32(); 
                    if (offset > 0 && offset < 0x0FFFFFFF) { 
                        traceMsg += "  -> GameAssembly.dll + " + offset + "\n";
                    }
                }
                send({ type: "info", payload: traceMsg });

                if (STOLEN_VEHICLE_TEAM_PTR !== null) {
                    send({ type: "hook", payload: "[INJECT] Replacing with -> " + STOLEN_VEHICLE_TEAM_PTR + " (VehicleTeam)" });
                    retval.replace(STOLEN_VEHICLE_TEAM_PTR);
                } else {
                    send({ type: "error", payload: "[INJECT FAIL] VehicleTeam pointer is null!" });
                }
            }
        });
    } catch(e) { send({ type: "error", payload: "Failed hook get_Team: " + e }); }

    send({ type: "info", payload: "System Ready. Step 1: Open Vehicle Garage/Formation." });
}

rpc.exports = {
    setspoof: function(enabled) {
        SPOOF_ENABLED = enabled;
        return true;
    }
};

setTimeout(initHooks, 1000);