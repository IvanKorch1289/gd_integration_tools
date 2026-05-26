/**
 * GD Integration Tools - LSP Client
 *
 * LSP (Language Server Protocol) client implementation for GD Integration Tools.
 * Provides:
 * - Text document synchronization
 * - Code completion
 * - Hover documentation
 * - Code lens for run step
 * - Diagnostics
 */

import {
    LanguageClient,
    LanguageClientOptions,
    ServerOptions,
    TransportKind,
    TextDocumentSyncKind,
    TextDocumentChangeEvent,
    DidChangeTextDocumentParams,
    DidOpenTextDocumentParams,
    DidSaveTextDocumentParams,
    DidCloseTextDocumentParams,
} from 'vscode-languageclient';
import * as vscode from 'vscode';

/**
 * Custom LSP notification types for GD DSL
 */
export interface GdRunStepParams {
    textDocument: { uri: string };
    position?: { line: number; character: number };
}

export interface GdDocumentationParams {
    textDocument: { uri: string };
}

export interface GdRunStepResult {
    success: boolean;
    output?: string;
    error?: string;
}

export interface GdDocumentationResult {
    content: string;
    range?: {
        start: { line: number; character: number };
        end: { line: number; character: number };
    };
}

/**
 * GD LSP Client configuration
 */
export interface GdLspClientConfig {
    serverAddress: string;
    workspaceRoot: string;
    enabled: boolean;
}

/**
 * Creates and configures the GD LSP Client
 */
export function createGdLspClient(config: GdLspClientConfig): LanguageClient {
    const [host, port] = config.serverAddress.split(':');
    const portNum = parseInt(port || '8765', 10);

    const clientOptions: LanguageClientOptions = {
        documentSelector: [
            { language: 'gd-dsl' },
            { language: 'python', scheme: 'file' },
            { language: 'yaml', scheme: 'file' },
        ],
        textDocumentSyncOptions: {
            save: true,
            openClose: true,
            change: TextDocumentSyncKind.Incremental,
        },
        diagnosticCollectionName: 'gd-integration-tools',
        lifecycle: {
            initialize: (params, progress) => {
                progress.begin('Initializing GD Integration Tools LSP...');
                return {
                    capabilities: {
                        textDocumentSync: TextDocumentSyncKind.Incremental,
                        completionProvider: { resolveProvider: true, triggerCharacters: ['.', ':', '@'] },
                        hoverProvider: true,
                        codeLensProvider: { resolveProvider: true },
                        definitionProvider: true,
                        referencesProvider: true,
                        documentFormattingProvider: true,
                        renameProvider: true,
                    },
                };
            },
            initialized: () => {
                progress.end();
            },
        },
        errorHandler: {
            error: (error, message, count) => {
                console.error(`LSP Error (${count}):`, error, message);
                return { action: 'continue' as const };
            },
            closed: () => {
                console.warn('LSP connection closed, attempting restart');
                return { action: 'restart' as const, message: 'Connection closed' };
            },
        },
        middleware: {
            didChange: (event, next) => {
                // Custom middleware for change events
                return next(event);
            },
            didOpen: (event, next) => {
                // Custom middleware for open events
                return next(event);
            },
            didSave: (event, next) => {
                // Custom middleware for save events
                return next(event);
            },
            didClose: (event, next) => {
                // Custom middleware for close events
                return next(event);
            },
        },
    };

    const serverOptions: ServerOptions = {
        run: {
            command: process.platform === 'win32' ? '.cmd' : 'node',
            args: [
                '${workspaceFolder}/node_modules/@gd-integration/lsp-server/dist/index.js',
                `--port=${portNum}`,
            ],
            transport: TransportKind.ipc,
            options: {
                cwd: config.workspaceRoot,
                shell: true,
            },
        },
        debug: {
            command: process.platform === 'win32' ? 'cmd' : 'node',
            args: [
                '${workspaceFolder}/node_modules/@gd-integration/lsp-server/dist/index.js',
                `--port=${portNum}`,
                '--inspect',
            ],
            transport: TransportKind.ipc,
            options: {
                cwd: config.workspaceRoot,
                shell: true,
                env: { NODE_OPTIONS: '--inspect' },
            },
        },
    };

    return new LanguageClient(
        'gd-integration-tools-lsp',
        'GD Integration Tools Language Server',
        serverOptions,
        clientOptions
    );
}

/**
 * Register GD-specific handlers with the language client
 */
export function registerGdHandlers(client: LanguageClient): void {
    // Handle GD run step requests
    client.onRequest<GdRunStepResult>('gd/runStep', async (params: GdRunStepParams) => {
        try {
            // This would typically call the GD backend
            return { success: true, output: 'Step executed successfully' };
        } catch (error) {
            return { success: false, error: String(error) };
        }
    });

    // Handle GD documentation requests
    client.onRequest<GdDocumentationResult>('gd/documentation', async (params: GdDocumentationParams) => {
        try {
            // This would typically fetch documentation from the GD backend
            return {
                content: '<p>GD DSL Documentation</p>',
                range: undefined,
            };
        } catch (error) {
            return { content: `<p>Error fetching documentation: ${error}</p>` };
        }
    });
}

/**
 * Extension API for external access
 */
export function extendGdClient(client: LanguageClient): void {
    // Extend the client with GD-specific capabilities
    client.onRequest('gd/capabilities', () => ({
        syntaxHighlighting: true,
        hoverDocs: true,
        runStepCodeLens: true,
        autoComplete: true,
    }));
}
