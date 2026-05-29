/**
 * GD Integration Tools - VSCode Extension
 * K5 S19 W2: VSCode extension for GD Integration Tools
 *
 * Features:
 * - Syntax highlighting for GD DSL
 * - Hover docs
 * - 'Run step' CodeLens
 * - LSP client for enhanced language features
 */

import * as vscode from 'vscode';
import { LanguageClient, LanguageClientOptions, ServerOptions, TransportKind } from 'vscode-languageclient';

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
                return { action: 'continue' as const };
            },
            closed: () => {
                return { action: 'restart' as const, message: 'LSP connection closed' };
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
            if (client?.isReady()) {
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

            if (client?.isReady()) {
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

    context.subscriptions.push(runStepCommand, showDocsCommand);
}

/**
 * Deactivate the extension
 */
export async function deactivate(): Promise<void> {
    if (client) {
        await client.stop();
    }
}
