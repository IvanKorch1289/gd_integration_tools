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
import { LanguageClient } from 'vscode-languageclient/node';
/**
 * Custom LSP notification types for GD DSL
 */
export interface GdRunStepParams {
    textDocument: {
        uri: string;
    };
    position?: {
        line: number;
        character: number;
    };
}
export interface GdDocumentationParams {
    textDocument: {
        uri: string;
    };
}
export interface GdRunStepResult {
    success: boolean;
    output?: string;
    error?: string;
}
export interface GdDocumentationResult {
    content: string;
    range?: {
        start: {
            line: number;
            character: number;
        };
        end: {
            line: number;
            character: number;
        };
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
export declare function createGdLspClient(config: GdLspClientConfig): LanguageClient;
/**
 * Register GD-specific handlers with the language client
 */
export declare function registerGdHandlers(client: LanguageClient): void;
/**
 * Extension API for external access
 */
export declare function extendGdClient(client: LanguageClient): void;
//# sourceMappingURL=client.d.ts.map