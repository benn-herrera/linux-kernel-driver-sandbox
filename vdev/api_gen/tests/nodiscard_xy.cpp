#include "xy_api.hpp"
int main() { auto p = xy::Port::create(1); p.send(nullptr, 0); return 0; }
