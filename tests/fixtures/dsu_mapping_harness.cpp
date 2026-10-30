// Test adapters only. The methods marker is replaced with actual fs_mgr source.
#include <chrono>
#include <cassert>
#include <iostream>
#include <memory>
#include <string>
#include <string_view>
#include <vector>
#include <unistd.h>

struct Log {
    template <class T> Log& operator<<(const T&) { return *this; }
};
#define LOG(level) Log()
#define PLOG(level) Log()
#define CHECK(value) assert(value); Log()

struct State {
    bool can_dm = true, resolve_ok = true, dm_ok = true, loop_ok = true;
    bool optimize_ok = true, already_mapped = false, property_ok = true;
    bool split_ok = true, write_ok = true;
    int dm_calls = 0, loop_calls = 0, unmaps = 0, detached = 0, properties = 0;
    int fail_loop_at = 0;
    std::vector<std::string> files = {"one.img"};
    std::string property_path;
} state;

namespace android::base {
bool StartsWith(std::string_view value, std::string_view prefix) {
    return value.substr(0, prefix.size()) == prefix;
}
bool ConsumeSuffix(std::string_view* value, std::string_view suffix) {
    if (value->size() < suffix.size() || value->substr(value->size() - suffix.size()) != suffix)
        return false;
    value->remove_suffix(suffix.size());
    return true;
}
bool SetProperty(const std::string&, const std::string& path) {
    ++state.properties;
    state.property_path = path;
    return state.property_ok;
}
bool WriteStringToFile(const std::string&, const std::string&) { return state.write_ok; }
}

@@UTILITIES@@
struct FiemapWriter {
    static bool GetBlockDeviceForFile(const std::string&, std::string* device, bool* can_dm) {
        *device = "/dev/block/userdata";
        *can_dm = state.can_dm;
        return state.resolve_ok;
    }
};
struct SplitFiemap {
    static bool GetSplitFileList(const std::string&, std::vector<std::string>* files) {
        *files = state.files;
        return state.split_ok;
    }
};
struct LoopControl {};
struct AutoDetachLoopDevices {
    const std::vector<std::string>& devices;
    bool committed = false;
    AutoDetachLoopDevices(LoopControl&, const std::vector<std::string>& value) : devices(value) {}
    ~AutoDetachLoopDevices() { if (!committed) state.detached += devices.size(); }
    void Commit() { committed = true; }
};
bool CreateLoopDevice(LoopControl&, const std::string&, std::chrono::milliseconds,
                      std::string* result) {
    ++state.loop_calls;
    if (!state.loop_ok || state.loop_calls == state.fail_loop_at) return false;
    *result = "/dev/loop" + std::to_string(state.loop_calls);
    return true;
}
bool OptimizeLoopDevices(const std::vector<std::string>&) { return state.optimize_ok; }

class ImageManager {
  public:
    explicit ImageManager(std::string dir) : data_dir_(std::move(dir)) {}
    bool MapImageDevice(const std::string&, const std::chrono::milliseconds&, std::string*);
    bool MapWithLoopDevice(const std::string&, const std::chrono::milliseconds&, std::string*);
    bool IsImageMapped(const std::string&) { return state.already_mapped; }
    std::string GetImageHeaderPath(const std::string&) { return "/dev/null"; }
    std::string GetStatusPropertyName(const std::string&) { return "test.mapping"; }
    std::string GetStatusFilePath(const std::string&) { return "/unused/status"; }
    bool UnmapImageDevice(const std::string&, bool) { ++state.unmaps; return true; }
    bool MapWithDmLinear(int, const std::string&, const std::chrono::milliseconds&,
                         std::string* path) {
        ++state.dm_calls;
        *path = "/dev/mapper/image";
        return state.dm_ok;
    }
    bool MapWithLoopDeviceList(const std::vector<std::string>&, const std::string&,
                               const std::chrono::milliseconds&, std::string* path) {
        *path = "/dev/mapper/joined";
        return state.dm_ok;
    }
  private:
    std::string data_dir_;
    std::unique_ptr<int> partition_opener_ = std::make_unique<int>(0);
};

@@METHODS@@

int main(int argc, char** argv) {
    if (argc != 2) return 2;
    std::string scenario = argv[1], path;
    std::string directory = "/data/gsi/dsu/test/";
    if (scenario == "non_dsu") directory = "/data/gsi/remount/";
    if (scenario == "prefix_lookalike") directory = "/data/gsi/dsu-other/";
    if (scenario == "dsu_root") directory = "/data/gsi/dsu";
    ImageManager manager(directory);
    const auto timeout = std::chrono::milliseconds(10000);
    bool ok;
    if (scenario.rfind("helper_", 0) == 0) {
        if (scenario == "helper_split" || scenario == "helper_split_failure" || scenario == "helper_second_attach_failure")
            state.files = {"one.img", "two.img"};
        if (scenario == "helper_empty") state.files.clear();
        if (scenario == "helper_optimize_failure") state.optimize_ok = false;
        if (scenario == "helper_split_failure") state.dm_ok = false;
        if (scenario == "helper_second_attach_failure") state.fail_loop_at = 2;
        if (scenario == "helper_status_failure") state.write_ok = false;
        ok = manager.MapWithLoopDevice("userdata_gsi", timeout, &path);
        if (scenario == "helper_split") return !(ok && path == "/dev/mapper/joined");
        if (scenario == "helper_empty") return !(!ok && state.loop_calls == 0);
        if (scenario == "helper_optimize_failure") return !(!ok && state.detached == 1);
        if (scenario == "helper_split_failure") return !(!ok && state.detached == 2);
        if (scenario == "helper_second_attach_failure") return !(!ok && state.loop_calls == 2 && state.detached == 1);
        if (scenario == "helper_status_failure") return !(!ok && state.detached == 1);
        return 2;
    }
    if (scenario != "device_mapper") state.can_dm = false;
    if (scenario == "loop_failure") state.loop_ok = false;
    if (scenario == "property_failure") state.property_ok = false;
    if (scenario == "resolve_failure") state.resolve_ok = false;
    if (scenario == "already_mapped") state.already_mapped = true;
    ok = manager.MapImageDevice("userdata_gsi", timeout, &path);
    if (scenario == "device_mapper" || scenario == "ramdisk")
        return !(ok && state.dm_calls == 1 && state.loop_calls == 0 && state.properties == 1);
    if (scenario == "non_dsu" || scenario == "prefix_lookalike" || scenario == "resolve_failure" || scenario == "already_mapped")
        return !(!ok && state.dm_calls == 0 && state.loop_calls == 0 && state.properties == 0);
    if (scenario == "dsu_loop" || scenario == "dsu_root")
        return !(ok && state.dm_calls == 0 && state.loop_calls == 1 && state.property_path == "/dev/loop1");
    if (scenario == "loop_failure")
        return !(!ok && state.dm_calls == 0 && state.properties == 0);
    if (scenario == "property_failure")
        return !(!ok && state.loop_calls == 1 && state.unmaps == 1);
    return 2;
}
