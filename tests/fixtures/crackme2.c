#include <stdio.h>
#include <string.h>

/* The password is never stored as text: each letter is checked by itself. */
static int check(const char *s) {
    if (strlen(s) != 4) return 0;
    if (s[0] != 'd') return 0;
    if (s[1] != 'o') return 0;
    if ((s[2] ^ 0x20) != 'G') return 0;
    if (s[3] != '!') return 0;
    return 1;
}

int main(void) {
    char input[32];
    printf("Password: ");
    scanf("%31s", input);
    puts(check(input) ? "Yes!" : "No.");
    return 0;
}
