#pragma once
// Minimal test framework (~60 lines) so the engine has zero third-party dependencies.
// TEST("name") { CHECK(cond); CHECK_EQ(a, b); }   Run all, or filter: lob_tests <substring>
#include <cstdio>
#include <cstring>
#include <exception>
#include <functional>
#include <sstream>
#include <string>
#include <vector>

namespace minitest {

struct Case { const char* name; std::function<void()> fn; };
inline std::vector<Case>& registry() { static std::vector<Case> r; return r; }
inline int& failures() { static int f = 0; return f; }

struct Registrar { Registrar(const char* n, std::function<void()> f) { registry().push_back({n, std::move(f)}); } };

template <class T>
std::string show(const T& v) {
    if constexpr (requires(std::ostream& os) { os << v; }) { std::ostringstream os; os << v; return os.str(); }
    else return "<value>";
}

inline void fail(const char* file, int line, const std::string& msg) {
    ++failures();
    std::printf("    %s:%d: %s\n", file, line, msg.c_str());
}

inline int run(int argc, char** argv) {
    const char* filter = argc > 1 ? argv[1] : nullptr;
    int ran = 0, failed_cases = 0;
    for (auto& c : registry()) {
        if (filter && !std::strstr(c.name, filter)) continue;
        ++ran;
        int before = failures();
        try { c.fn(); }
        catch (const std::exception& e) { fail("<exception>", 0, e.what()); }
        catch (...) { fail("<exception>", 0, "unknown exception"); }
        bool ok = failures() == before;
        failed_cases += !ok;
        std::printf("[%s] %s\n", ok ? " ok " : "FAIL", c.name);
    }
    std::printf("\n%d/%d test cases passed\n", ran - failed_cases, ran);
    return failed_cases == 0 ? 0 : 1;
}

}  // namespace minitest

#define MT_CAT2(a, b) a##b
#define MT_CAT(a, b) MT_CAT2(a, b)
#define TEST(name)                                                                     \
    static void MT_CAT(mt_fn_, __LINE__)();                                            \
    static minitest::Registrar MT_CAT(mt_reg_, __LINE__)(name, MT_CAT(mt_fn_, __LINE__)); \
    static void MT_CAT(mt_fn_, __LINE__)()

#define CHECK(cond) \
    do { if (!(cond)) minitest::fail(__FILE__, __LINE__, "CHECK(" #cond ") failed"); } while (0)

#define CHECK_EQ(a, b)                                                                              \
    do {                                                                                            \
        const auto& mt_a = (a); const auto& mt_b = (b);                                             \
        if (!(mt_a == mt_b))                                                                        \
            minitest::fail(__FILE__, __LINE__,                                                      \
                           "CHECK_EQ(" #a ", " #b "): " + minitest::show(mt_a) + " != " + minitest::show(mt_b)); \
    } while (0)

// Stop the current test case (e.g. before indexing into a vector that is too short).
#define REQUIRE(cond) \
    do { if (!(cond)) { minitest::fail(__FILE__, __LINE__, "REQUIRE(" #cond ") failed"); return; } } while (0)
