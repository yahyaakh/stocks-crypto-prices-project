cmake_minimum_required(VERSION 3.20)
project(lob_engine LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)  # benchmarks are meaningless at -O0
endif()

option(LOB_SANITIZE "Build with AddressSanitizer + UndefinedBehaviorSanitizer" OFF)

add_compile_options(-Wall -Wextra -Wpedantic -Wshadow -Wconversion -Wno-sign-conversion)
if(LOB_SANITIZE)
  add_compile_options(-fsanitize=address,undefined -fno-omit-frame-pointer)
  add_link_options(-fsanitize=address,undefined)
endif()

# The engine itself: a dependency-free static library.
add_library(lob src/order_book.cpp)
target_include_directories(lob PUBLIC include)

enable_testing()
add_executable(lob_tests tests/test_order_book.cpp)
target_link_libraries(lob_tests PRIVATE lob)
add_test(NAME lob_tests COMMAND lob_tests)

if(EXISTS ${CMAKE_CURRENT_SOURCE_DIR}/bench/bench.cpp)
  add_executable(lob_bench bench/bench.cpp)
  target_link_libraries(lob_bench PRIVATE lob)
endif()

if(EXISTS ${CMAKE_CURRENT_SOURCE_DIR}/tools/lobster_replay.cpp)
  add_executable(lobster_replay tools/lobster_replay.cpp)
  target_link_libraries(lobster_replay PRIVATE lob)
endif()
