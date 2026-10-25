// RekordTrakt bridge helper: creates and removes the Windows MIDI Services loopback pair the translator uses
// (app side <-> Rekordbox side), so users don't need the MIDI Settings tools. Prints one JSON object per run.
//
//   rekordtrakt-bridge check
//   rekordtrakt-bridge create --name-a "RekordTrakt App" --name-b "RekordTrakt Bridge" --id-a rekordtraktapp --id-b rekordtraktbridge
//   rekordtrakt-bridge remove --association <guid>
//   rekordtrakt-bridge list                     active (this boot) and saved (MIDI Settings) loopback pairs
//   rekordtrakt-bridge ports                    every MIDI input port with the device unit it belongs to
//
// Loopbacks made here are "transient": they last until the MIDI service restarts (normally a reboot), even after
// this helper exits. Creating a pair whose unique ids already exist fails; remove it first, or reuse it.

using System.Text.Json.Nodes;
using Windows.Devices.Midi2;
using Windows.Devices.Midi2.Enumeration;
using Windows.Devices.Midi2.Enumeration.Legacy;
using Windows.Devices.Midi2.Transports.Loopback;

const int MinimumBuild = 26200;   // Windows 11 25H2, the first version that supports the Windows MIDI Services API

// JsonObject rather than serialised anonymous types: the published helper is trimmed, which turns off reflection.
static JsonObject Obj(params (string Key, JsonNode? Value)[] items)
{
    var o = new JsonObject();
    foreach (var (key, value) in items) o[key] = value;
    return o;
}

static int Emit(JsonObject result, bool ok)
{
    Console.WriteLine(result.ToJsonString());
    return ok ? 0 : 1;
}

static int Fail(string command, string error) => Emit(Obj(("command", command), ("success", false), ("error", error)), false);

static string? Arg(string[] args, string name)
{
    int i = Array.IndexOf(args, name);
    return i >= 0 && i + 1 < args.Length ? args[i + 1] : null;
}

static bool? SystemProvidedApi()
{
    try { return MidiApi.IsSystemProvided(); }
    catch { return null; }      // older API copy without IMidiApiStatics2
}

string command = args.Length > 0 ? args[0] : "check";
int build = Environment.OSVersion.Version.Build;

if (command == "check")
{
    bool windowsOk = build >= MinimumBuild;
    bool service = false, loopback = false;
    string? error = null;
    try
    {
        service = MidiApi.EnsureServiceAvailable();
        loopback = service && MidiLoopbackManager.IsTransportAvailable;
    }
    catch (Exception e) { error = e.Message; }
    return Emit(Obj(
        ("command", command),
        ("windows_build", build),
        ("windows_supported", windowsOk),
        ("api_system_provided", SystemProvidedApi()),
        ("service_available", service),
        ("loopback_transport", loopback),
        ("usable", windowsOk && service && loopback),
        ("error", error)), windowsOk && service && loopback);
}

if (command == "create")
{
    string nameA = Arg(args, "--name-a") ?? "RekordTrakt App";
    string nameB = Arg(args, "--name-b") ?? "RekordTrakt Bridge";
    string idA = Arg(args, "--id-a") ?? "rekordtraktapp";
    string idB = Arg(args, "--id-b") ?? "rekordtraktbridge";
    try
    {
        if (!MidiApi.EnsureServiceAvailable())
            return Fail(command, "the MIDI service could not be started");
        if (!MidiLoopbackManager.IsTransportAvailable)
            return Fail(command, "the loopback transport is not available");

        var a = new MidiLoopbackEndpointDefinition { Name = nameA, UniqueId = idA, Description = "RekordTrakt: translator side" };
        var b = new MidiLoopbackEndpointDefinition { Name = nameB, UniqueId = idB, Description = "RekordTrakt: Rekordbox side" };
        MidiLoopbackCreationResponse response = MidiLoopbackManager.CreateTransientLoopback(new MidiLoopbackCreationConfig(a, b));
        if (!response.Success)
            return Fail(command, "creation failed (a pair with these unique ids may already exist)");

        var entry = response.CreatedLoopbackEntry;
        return Emit(Obj(
            ("command", command),
            ("success", true),
            ("association_id", entry.AssociationId),
            ("endpoint_a", Obj(("name", entry.EndpointA.Name), ("id", entry.EndpointA.EndpointDeviceId))),
            ("endpoint_b", Obj(("name", entry.EndpointB.Name), ("id", entry.EndpointB.EndpointDeviceId)))), true);
    }
    catch (Exception e) { return Fail(command, e.Message); }
}

if (command == "list")
{
    try
    {
        if (!MidiApi.EnsureServiceAvailable())
            return Fail(command, "the MIDI service could not be started");
        var active = new JsonArray();
        foreach (var e in MidiLoopbackManager.GetActiveLoopbackEntries())
            active.Add((JsonNode)Obj(
                ("association_id", e.AssociationId),
                ("endpoint_a", Obj(("name", e.EndpointA.Name), ("id", e.EndpointA.EndpointDeviceId))),
                ("endpoint_b", Obj(("name", e.EndpointB.Name), ("id", e.EndpointB.EndpointDeviceId))),
                ("muted", e.IsMuted),
                ("muted_for_feedback", e.IsMutedForFeedback)));
        var saved = new JsonArray();
        foreach (var e in MidiLoopbackManager.GetSavedLoopbackEntries())
            saved.Add((JsonNode)Obj(
                ("association_id", e.AssociationId),
                ("name_a", e.EndpointDefinitionA.Name),
                ("name_b", e.EndpointDefinitionB.Name),
                ("muted", e.IsMuted)));
        return Emit(Obj(("command", command), ("success", true), ("active", active), ("saved", saved)), true);
    }
    catch (Exception e) { return Fail(command, e.Message); }
}

if (command == "ports")
{
    // Windows numbers identical port names ("TRAKTOR X1 MK3", "2 - TRAKTOR X1 MK3") in the order the units appear,
    // which can change after a replug. "unit" is the USB device's instance id: it carries the serial number when
    // the device has one (otherwise the USB socket it's in), so it tells two identical controllers apart.
    try
    {
        if (!MidiApi.EnsureServiceAvailable())
            return Fail(command, "the MIDI service could not be started");
        var ports = new JsonArray();
        foreach (var p in MidiLegacyPortDeviceInformation.FindAll(Midi1PortFlow.MidiMessageSource))
            ports.Add((JsonNode)Obj(("name", p.Name), ("number", p.Number), ("unit", p.ParentDeviceInstanceId),
                                    ("container", p.ContainerId.ToString())));
        return Emit(Obj(("command", command), ("success", true), ("ports", ports)), true);
    }
    catch (Exception e) { return Fail(command, e.Message); }
}

if (command == "remove")
{
    string? association = Arg(args, "--association");
    if (association is null || !Guid.TryParse(association, out Guid id))
        return Fail(command, "--association <guid> is required");
    try
    {
        MidiLoopbackRemovalResponse response = MidiLoopbackManager.RemoveTransientLoopback(new MidiLoopbackRemovalConfig(id));
        return Emit(Obj(("command", command), ("success", response.Success)), response.Success);
    }
    catch (Exception e) { return Fail(command, e.Message); }
}

return Fail(command, "commands: check | create | remove | list | ports");
