/**
 * GD Integration Tools - VSCode Extension
 * K5 S19 W2 + S33 W5: VSCode extension for GD Integration Tools
 *
 * Features:
 * - Syntax highlighting for GD DSL
 * - Hover docs
 * - 'Run step' CodeLens
 * - LSP client for enhanced language features
 * - Wizard commands: wizardRoute, wizardPlugin (S33 W5)
 * - DSL-aware editing for .dsl.yaml and route.toml
 */

import * as vscode from 'vscode';
import { LanguageClient, LanguageClientOptions, ServerOptions, TransportKind, ErrorAction, CloseAction, State } from 'vscode-languageclient/node';

/**
 * LSP Client instance for GD Integration Tools
 */
let client: LanguageClient | undefined;

/**
 * Activate the extension
 * Called by VSCode when the extension is first activated
 */
export async function activate(context: vscode.ExtensionContext): Promise<void> {
    // Check if LSP is enabled in configuration
    const config = vscode.workspace.getConfiguration('gdIntegrationTools');
    const lspEnabled = config.get<boolean>('lsp.enabled', true);

    if (!lspEnabled) {
        vscode.window.showInformationMessage('GD Integration Tools LSP client is disabled');
        return;
    }

    const serverAddress = config.get<string>('lsp.server', 'localhost:8765');
    const [host, port] = serverAddress.split(':');
    const portNum = parseInt(port || '8765', 10);

    // Configure LSP client
    const clientOptions: LanguageClientOptions = {
        documentSelector: [
            { language: 'gd-dsl' },
            { language: 'python', scheme: 'file', pattern: '**/src/backend/**/*.py' },
            { language: 'yaml', scheme: 'file', pattern: '**/routes/**/*.yaml' }
        ],
        synchronize: {
            fileEvents: vscode.workspace.createFileSystemWatcher('**/*.gd'),
        },
        initializationOptions: {
            workspaceFolder: vscode.workspace.workspaceFolders?.[0]?.uri.toString(),
        },
        errorHandler: {
            error: (error, message, count) => {
                vscode.window.showErrorMessage(`LSP Error: ${error.message}`);
                return { action: ErrorAction.Continue };
            },
            closed: () => {
                return { action: CloseAction.Restart, message: 'LSP connection closed' };
            },
        },
    };

    // Server options for the LSP server
    const serverOptions: ServerOptions = {
        run: {
            command: 'node',
            args: ['${workspaceFolder}/node_modules/@gd-integration/lsp-server/dist/index.js', `--port=${portNum}`],
            transport: TransportKind.ipc,
            options: { cwd: vscode.workspace.workspaceFolders?.[0]?.uri.fsPath },
        },
        debug: {
            command: 'node',
            args: ['${workspaceFolder}/node_modules/@gd-integration/lsp-server/dist/index.js', `--port=${portNum}`, '--inspect'],
            transport: TransportKind.ipc,
            options: {
                cwd: vscode.workspace.workspaceFolders?.[0]?.uri.fsPath,
                env: { NODE_OPTIONS: '--inspect' },
            },
        },
    };

    // Create and start the language client
    client = new LanguageClient(
        'gd-integration-tools-lsp',
        'GD Integration Tools LSP',
        serverOptions,
        clientOptions
    );

    // Register command handlers
    registerCommands(context);

    // Start the client
    try {
        await client.start();
        context.subscriptions.push({
            dispose: () => client?.stop(),
        });
        vscode.window.showInformationMessage('GD Integration Tools LSP client started');
    } catch (error) {
        vscode.window.showErrorMessage(`Failed to start LSP client: ${error}`);
    }
}

/**
 * Register VSCode commands
 */
function registerCommands(context: vscode.ExtensionContext): void {
    // Run Step command
    const runStepCommand = vscode.commands.registerCommand(
        'gd-integration-tools.runStep',
        async (uri?: vscode.Uri) => {
            const document = uri
                ? await vscode.workspace.openTextDocument(uri)
                : vscode.window.activeTextEditor?.document;

            if (!document) {
                vscode.window.showWarningMessage('No document found');
                return;
            }

            const editor = await vscode.window.showTextDocument(document);
            const selection = editor.selection;

            // Send document text to LSP for processing
            if (client?.state === State.Running) {
                const params = {
                    textDocument: { uri: document.uri.toString() },
                    position: { line: selection.start.line, character: selection.start.character },
                };
                client.sendRequest('gd/runStep', params).then(
                    (result) => {
                        if (result) {
                            vscode.window.showInformationMessage(`Step result: ${JSON.stringify(result)}`);
                        }
                    },
                    (error) => {
                        vscode.window.showErrorMessage(`Run step failed: ${error}`);
                    }
                );
            }
        }
    );

    // Show Docs command
    const showDocsCommand = vscode.commands.registerCommand(
        'gd-integration-tools.showDocs',
        async (uri?: vscode.Uri) => {
            const document = uri
                ? await vscode.workspace.openTextDocument(uri)
                : vscode.window.activeTextEditor?.document;

            if (!document) {
                vscode.window.showWarningMessage('No document found');
                return;
            }

            if (client?.state === State.Running) {
                const params = {
                    textDocument: { uri: document.uri.toString() },
                };
                client.sendRequest('gd/documentation', params).then(
                    (result) => {
                        if (result) {
                            const panel = vscode.window.createWebviewPanel(
                                'gd-docs',
                                'GD Documentation',
                                vscode.ViewColumn.Beside,
                                {}
                            );
                            panel.webview.html = `<html><body>${result}</body></html>`;
                        }
                    },
                    (error) => {
                        vscode.window.showErrorMessage(`Show docs failed: ${error}`);
                    }
                );
            }
        }
    );

    // GD Wizard Route command
    const wizardRouteCommand = vscode.commands.registerCommand(
        "gd-integration-tools.wizardRoute",
        async () => {
            const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
            if (!workspaceFolder) {
                vscode.window.showWarningMessage("No workspace folder open");
                return;
            }
            const config = vscode.workspace.getConfiguration("gdIntegrationTools");
            const pythonCmd = config.get<string>("pythonCommand", "uv run python");
            const terminal = vscode.window.createTerminal({
                name: "GD Wizard Route",
                cwd: workspaceFolder.uri.fsPath,
            });
            terminal.sendText(`${pythonCmd} tools/wizards/route_wizard.py`);
            terminal.show();
        }
    );

    // GD Wizard Plugin command
    const wizardPluginCommand = vscode.commands.registerCommand(
        "gd-integration-tools.wizardPlugin",
        async () => {
            const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
            if (!workspaceFolder) {
                vscode.window.showWarningMessage("No workspace folder open");
                return;
            }
            const config = vscode.workspace.getConfiguration("gdIntegrationTools");
            const pythonCmd = config.get<string>("pythonCommand", "uv run python");
            const terminal = vscode.window.createTerminal({
                name: "GD Wizard Plugin",
                cwd: workspaceFolder.uri.fsPath,
            });
            terminal.sendText(`${pythonCmd} tools/wizards/plugin_wizard.py`);
            terminal.show();
        }
    );

    // GD Validate Route command
    const validateRouteCommand = vscode.commands.registerCommand(
        "gd-integration-tools.validateRoute",
        async () => {
            const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
            if (!workspaceFolder) {
                return;
            }
            const terminal = vscode.window.createTerminal({
                name: "GD Validate Route",
                cwd: workspaceFolder.uri.fsPath,
            });
            terminal.sendText("make routes");
            terminal.show();
        }
    );

    // GD Open Routes Folder
    const openRoutesCommand = vscode.commands.registerCommand(
        "gd-integration-tools.openRoutesFolder",
        async () => {
            const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
            if (!workspaceFolder) {
                return;
            }
            const config = vscode.workspace.getConfiguration("gdIntegrationTools");
            const routesDir = config.get<string>("routesDir", "routes");
            const folderUri = vscode.Uri.joinPath(workspaceFolder.uri, routesDir);
            await vscode.commands.executeCommand("revealFileInOS", folderUri);
        }
    );

    // GD Open Extensions Folder
    const openExtensionsCommand = vscode.commands.registerCommand(
        "gd-integration-tools.openExtensionsFolder",
        async () => {
            const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
            if (!workspaceFolder) {
                return;
            }
            const config = vscode.workspace.getConfiguration("gdIntegrationTools");
            const extensionsDir = config.get<string>("extensionsDir", "extensions");
            const folderUri = vscode.Uri.joinPath(workspaceFolder.uri, extensionsDir);
            await vscode.commands.executeCommand("revealFileInOS", folderUri);
        }
    );

    context.subscriptions.push(
        runStepCommand,
        showDocsCommand,
        wizardRouteCommand,
        wizardPluginCommand,
        validateRouteCommand,
        openRoutesCommand,
        openExtensionsCommand,
    );
}

/**
 * Deactivate the extension
 */
export async function deactivate(): Promise<void> {
    if (client) {
        await client.stop();
    }
}
