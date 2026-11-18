"""Exercise the production font-upload callbacks, including cleanup and retry."""
from pathlib import Path
import unittest
from test_reading_ui_regressions import method, run_cpp

ROOT = Path(__file__).resolve().parents[2]


class FontUploadTest(unittest.TestCase):
    def test_upload_lifecycle_and_failures(self):
        source = (ROOT / 'src/network/CrossPointWebServer.cpp').read_text()
        header = (ROOT / 'src/network/CrossPointWebServer.h').read_text()
        state = method(header, 'struct FontUploadState')
        callbacks = '\n'.join([
            method(source, 'void CrossPointWebServer::handleFontUploadData()'),
            method(source, 'void CrossPointWebServer::handleFontUpload()'),
        ])
        run_cpp(r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <map>
#include <memory>
#include <string>
#include <vector>
template<class... T> void logMessage(T&&...) {}
#define LOG_DBG(...) logMessage(__VA_ARGS__)
#define LOG_ERR(...) logMessage(__VA_ARGS__)
void resetTaskWatchdogIfSubscribed() {}
struct String : std::string {
 using std::string::string;
 void replace(char from, char to) { std::replace(begin(), end(), from, to); }
};
enum { UPLOAD_FILE_START, UPLOAD_FILE_WRITE, UPLOAD_FILE_END, UPLOAD_FILE_ABORTED };
struct HTTPUpload {
 int status = UPLOAD_FILE_START;
 String filename = "TestFont_14.cpfont";
 size_t currentSize = 0;
 uint8_t buf[4096]{};
};
namespace memory { using ByteBuffer = std::unique_ptr<uint8_t[]>; }
bool allocationOk = true;
int allocations = 0;
memory::ByteBuffer makeWebBuffer(size_t size) {
 ++allocations;
 return allocationOk ? std::make_unique<uint8_t[]>(size) : nullptr;
}
bool writesOk = true;
struct HalFile {
 std::shared_ptr<std::vector<uint8_t>> data;
 explicit operator bool() const { return data != nullptr; }
 bool isOpen() const { return data != nullptr; }
 void close() { data.reset(); }
 size_t write(const uint8_t* bytes, size_t count) {
  assert(data);
  if (!writesOk) return 0;
  data->insert(data->end(), bytes, bytes + count);
  return count;
 }
};
struct {
 bool openOk = true;
 std::map<std::string, std::shared_ptr<std::vector<uint8_t>>> files;
 bool openFileForWrite(const char*, const char* path, HalFile& file) {
  if (!openOk) return false;
  auto data = std::make_shared<std::vector<uint8_t>>();
  files[path] = data;
  file.data = data;
  return true;
 }
 void remove(const char* path) { files.erase(path); }
} Storage;
struct Registry {};
struct {
 Registry value;
 int refreshes = 0;
 Registry& registry() { return value; }
 void markRegistryDirty() { ++refreshes; }
} sdFontSystem;
bool directoryOk = true;
struct FontInstaller {
 explicit FontInstaller(Registry&) {}
 static bool safeName(const char* name) {
  return name && *name && std::strspn(name, "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-") == std::strlen(name);
 }
 static bool isValidFamilyName(const char* name) { return safeName(name); }
 static bool hasExtension(const char* name, const char* ext) {
  std::string s(name);
  const auto dot = s.rfind('.');
  return dot != std::string::npos && s.substr(dot) == ext && safeName(s.substr(0, dot).c_str());
 }
 static bool isValidCpfontFilename(const char* name) { return hasExtension(name, ".cpfont"); }
 static bool isValidVectorFontFilename(const char* name) { return hasExtension(name, ".ttf") || hasExtension(name, ".otf"); }
 bool ensureFamilyDir(const char*) { return directoryOk; }
 static void buildFontPath(const char* family, const char* name, char* path, size_t size) {
  snprintf(path, size, "/fonts/%s/%s", family, name);
 }
};
namespace HalMemory {
size_t psramBytes = 0;
struct Heap { size_t totalBytes; };
Heap getPsramHeap() { return {psramBytes}; }
}
struct Server {
 HTTPUpload pending;
 String family = "TestFont";
 int response = 0;
 HTTPUpload& upload() { return pending; }
 String arg(const char* key) { assert(std::strcmp(key, "family") == 0); return family; }
 void send(int status, const char*, const char*) { response = status; }
};
class CrossPointWebServer {
 public:
 Server* server;
 bool cancelled = false;
 bool dropUploadIfCancelled() { return cancelled; }
 void handleFontUploadData();
 void handleFontUpload();
''' + state + r''' fontUpload;
};
''' + callbacks + r'''
const char* path = "/fonts/TestFont/TestFont_14.cpfont";
void event(CrossPointWebServer& web, int status) {
 web.server->pending.status = status;
 web.handleFontUploadData();
}
void bytes(CrossPointWebServer& web, const std::vector<uint8_t>& data) {
 assert(data.size() <= sizeof(web.server->pending.buf));
 std::memcpy(web.server->pending.buf, data.data(), data.size());
 web.server->pending.currentSize = data.size();
 event(web, UPLOAD_FILE_WRITE);
}
void finish(CrossPointWebServer& web, int expected) {
 event(web, UPLOAD_FILE_END);
 assert(!web.fontUpload.file && !web.fontUpload.buffer && web.fontUpload.bufferPos == 0);
 web.handleFontUpload();
 assert(web.server->response == expected);
 assert(!web.fontUpload.valid);
}
void success(CrossPointWebServer& web) {
 event(web, UPLOAD_FILE_START);
 assert(web.fontUpload.valid && web.fontUpload.file && web.fontUpload.buffer);
 std::vector<uint8_t> first(4096, 0xA5), tail(113, 0x5A);
 std::memcpy(first.data(), "CPFONT\0\0", 8);
 bytes(web, first);
 bytes(web, tail);
 finish(web, 200);
 first.insert(first.end(), tail.begin(), tail.end());
 assert(*Storage.files.at(path) == first);
 // A later POST without a file must not replay an earlier success.
 web.handleFontUpload();
 assert(web.server->response == 400);
}
int main() {
 Server server;
 CrossPointWebServer web{};
 web.server = &server;
 // Startup may have reserved a buffer; each new request must still allocate.
 web.fontUpload.buffer = makeWebBuffer(4096);
 success(web);
 success(web); // Consecutive files in a family.
 assert(sdFontSystem.refreshes == 2);

 allocationOk = false;
 event(web, UPLOAD_FILE_START);
 assert(!web.fontUpload.valid && !web.fontUpload.file && !web.fontUpload.buffer);
 finish(web, 400);
 allocationOk = true;
 success(web); // A failed allocation must not poison the next request.

 Storage.openOk = false;
 event(web, UPLOAD_FILE_START);
 assert(!web.fontUpload.valid && !web.fontUpload.buffer);
 finish(web, 400);
 Storage.openOk = true;

 directoryOk = false;
 const auto before = allocations;
 event(web, UPLOAD_FILE_START);
 finish(web, 400);
 assert(allocations == before);
 directoryOk = true;

 server.family = "../escape";
 event(web, UPLOAD_FILE_START);
 finish(web, 400);
 assert(allocations == before);
 server.family = "TestFont";
 server.pending.filename = "../evil.cpfont";
 event(web, UPLOAD_FILE_START);
 finish(web, 400);
 assert(allocations == before);
 server.pending.filename = "TestFont_14.cpfont";

 event(web, UPLOAD_FILE_START);
 bytes(web, std::vector<uint8_t>(12, 0x42));
 finish(web, 400);
 assert(Storage.files.count(path) == 0);
 success(web);

 event(web, UPLOAD_FILE_START);
 std::vector<uint8_t> chunk(4096, 0);
 std::memcpy(chunk.data(), "CPFONT\0\0", 8);
 writesOk = false;
 bytes(web, chunk);
 finish(web, 400);
 writesOk = true;
 assert(Storage.files.count(path) == 0);
 success(web);

 event(web, UPLOAD_FILE_START);
 bytes(web, std::vector<uint8_t>{'C','P','F','O','N','T',0,0,4});
 event(web, UPLOAD_FILE_ABORTED);
 assert(!web.fontUpload.valid && !web.fontUpload.buffer && !web.fontUpload.file);
 assert(Storage.files.count(path) == 0);
 web.handleFontUpload();
 assert(server.response == 400);
 success(web);

 // PSRAM targets retain their existing vector-font capability gate.
 server.pending.filename = "TestFont.ttf";
 event(web, UPLOAD_FILE_START);
 finish(web, 400);
 HalMemory::psramBytes = 8 * 1024 * 1024;
 event(web, UPLOAD_FILE_START);
 assert(web.fontUpload.valid && web.fontUpload.isVector);
 bytes(web, std::vector<uint8_t>{0,1,0,0,0,0,0,0,1});
 finish(web, 200);
 assert(Storage.files.at("/fonts/TestFont/TestFont.ttf")->size() == 9);
}
''')


if __name__ == '__main__':
    unittest.main()
