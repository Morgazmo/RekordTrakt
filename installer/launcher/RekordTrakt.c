/* RekordTrakt.exe: runs the app on the Python runtime installed beside it (runtime\python313.dll), as this process,
   so Windows shows RekordTrakt (its name, icon and version) rather than Python. Arguments pass through to the app
   (--login, --quit, --restore-rekordbox...). */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shellapi.h>
#include <stdlib.h>
#include <wchar.h>

#ifndef PYTHON_DLL
#define PYTHON_DLL L"python313.dll"
#endif

typedef int (*PyMainFunc)(int, wchar_t **);

static const wchar_t *BOOT =
    L"import sys; sys.frozen = True; from rekordtrakt.shell.app import main; sys.exit(main(sys.argv[1:]))";

static int fail(const wchar_t *text)
{
    MessageBoxW(NULL, text, L"RekordTrakt", MB_ICONERROR | MB_OK);
    return 1;
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR command_line, int show)
{
    (void)instance; (void)previous; (void)command_line; (void)show;     /* the full command line is read below */
    wchar_t dir[MAX_PATH], runtime[MAX_PATH], dll[MAX_PATH];
    DWORD n = GetModuleFileNameW(NULL, dir, MAX_PATH);
    if (n == 0 || n >= MAX_PATH)
        return fail(L"RekordTrakt can't find where it's installed.");
    *wcsrchr(dir, L'\\') = L'\0';
    swprintf(runtime, MAX_PATH, L"%s\\runtime", dir);
    swprintf(dll, MAX_PATH, L"%s\\%s", runtime, PYTHON_DLL);

    SetDllDirectoryW(runtime);
    HMODULE python = LoadLibraryExW(dll, NULL, LOAD_WITH_ALTERED_SEARCH_PATH);
    if (!python)
        return fail(L"RekordTrakt can't start: part of it is missing. Reinstall RekordTrakt.");
    PyMainFunc py_main = (PyMainFunc)GetProcAddress(python, "Py_Main");
    if (!py_main)
        return fail(L"RekordTrakt can't start: part of it is damaged. Reinstall RekordTrakt.");

    int argc = 0;
    wchar_t **argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    if (!argv)
        return fail(L"RekordTrakt can't read how it was started.");
    wchar_t **args = calloc((size_t)argc + 4, sizeof(wchar_t *));
    if (!args)
        return fail(L"RekordTrakt is out of memory.");
    int i = 0;
    args[i++] = argv[0];
    args[i++] = L"-I";                  /* isolated: no environment variables or user site packages */
    args[i++] = L"-c";
    args[i++] = (wchar_t *)BOOT;
    for (int a = 1; a < argc; a++)
        args[i++] = argv[a];
    int code = py_main(i, args);
    free(args);
    LocalFree(argv);
    return code;
}
