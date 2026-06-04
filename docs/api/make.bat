@ECHO OFF

REM Minimal make.bat for Sphinx documentation (S40 W4 — auto-generated API reference).
REM
REM Использование:
REM   make.bat html         — собрать HTML в _build\html\
REM   make.bat clean        — удалить _build\ и _apidoc\
REM   make.bat apidoc       — только sphinx-apidoc (регенерация RST-файлов)
REM   make.bat html-noplot  — то же, что html
REM   make.bat linkcheck    — проверить все внешние ссылки
REM   make.bat help         — список целей
REM
REM Скрипт эквивалентен Makefile, но для Windows / cmd.exe.

REM Command line options for sphinx-build / sphinx-apidoc.
set SPHINXOPTS=-W --keep-going
set SPHINXBUILD=sphinx-build
set SPHINXAPIDOC=sphinx-apidoc

REM Paths: assume this batch file lives in docs\api\ of the repository.
set SOURCEDIR=.
set BUILDDIR=_build
set APIDOCDIR=_apidoc
set PROJECTDIR=..\..
set APISRC=%PROJECTDIR%\src\backend\dsl

REM Prefer local .venv binaries if present.
if exist "%PROJECTDIR%\.venv\Scripts\sphinx-build.exe" (
    set SPHINXBUILD=%PROJECTDIR%\.venv\Scripts\sphinx-build.exe
)
if exist "%PROJECTDIR%\.venv\Scripts\sphinx-apidoc.exe" (
    set SPHINXAPIDOC=%PROJECTDIR%\.venv\Scripts\sphinx-apidoc.exe
)

if "%1" == "" goto help
if "%1" == "help" goto help
if "%1" == "clean" goto clean
if "%1" == "apidoc" goto apidoc
if "%1" == "html" goto html
if "%1" == "html-noplot" goto html

REM Default: proxy to sphinx-build -M <target>.
%SPHINXBUILD% -M %1 %SOURCEDIR% %BUILDDIR% %SPHINXOPTS% %2 %3 %4 %5 %6 %7 %8 %9
goto end

:help
%SPHINXBUILD% -M help %SOURCEDIR% %BUILDDIR% %SPHINXOPTS%
goto end

:clean
if exist "%BUILDDIR%" rmdir /S /Q "%BUILDDIR%"
if exist "%APIDOCDIR%" rmdir /S /Q "%APIDOCDIR%"
echo Cleaned %BUILDDIR% and %APIDOCDIR%.
goto end

:apidoc
if not exist "%APIDOCDIR%" mkdir "%APIDOCDIR%"
echo Running sphinx-apidoc -^> %APIDOCDIR%\
%SPHINXAPIDOC% -f -e -M -T -o %APIDOCDIR% %APISRC%
goto end

:html
call :apidoc
echo Building HTML -^> %BUILDDIR%\html\
%SPHINXBUILD% -b html %SOURCEDIR% %BUILDDIR%\html %SPHINXOPTS%
echo.
echo Build finished. The HTML pages are in %BUILDDIR%\html\.
goto end

:end
