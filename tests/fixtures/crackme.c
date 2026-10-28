#include <stdio.h>
#include <string.h>

int main(void) {
    char input[64];
    printf("Enter password: ");
    if (scanf("%63s", input) != 1) return 1;
    if (strcmp(input, "c3rb3rus_r0cks") == 0) {
        puts("Correct! The flag is CTF{dogs_with_three_heads}");
    } else {
        puts("Wrong password.");
    }
    return 0;
}
