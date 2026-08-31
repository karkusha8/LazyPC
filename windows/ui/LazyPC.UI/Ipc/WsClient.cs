using System;
using System.IO;
using System.Net.WebSockets;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace LazyPC.UI.Ipc;

public sealed class WsClient : IDisposable
{
    private const string AgentUri =
        "ws://127.0.0.1:8765/ui";

    private ClientWebSocket? _socket;

    private readonly SemaphoreSlim _writeLock = new(1, 1);
    private readonly SemaphoreSlim _receiveLock = new(1, 1);

    public bool IsConnected =>
        _socket?.State == WebSocketState.Open;

    public async Task ConnectAsync(
        CancellationToken cancellationToken = default)
    {
        if (IsConnected)
            return;

        DisposeSocketOnly();

        var socket = new ClientWebSocket();

        try
        {
            Console.WriteLine(
                $"[IPC] Connecting UI -> Agent: {AgentUri}"
            );

            await socket.ConnectAsync(
                new Uri(AgentUri),
                cancellationToken
            );

            if (socket.State != WebSocketState.Open)
            {
                throw new InvalidOperationException(
                    $"WebSocket connected with unexpected state: {socket.State}"
                );
            }

            _socket = socket;

            Console.WriteLine(
                "[IPC] UI <-> Agent WebSocket CONNECTED"
            );
        }
        catch (Exception error)
        {
            Console.WriteLine(
                $"[IPC] WebSocket connection failed: {error}"
            );

            socket.Dispose();
            throw;
        }
    }

    public async Task SendAsync(
        object message,
        CancellationToken cancellationToken = default)
    {
        var socket = _socket;

        if (socket is null ||
            socket.State != WebSocketState.Open)
        {
            throw new InvalidOperationException(
                "UI -> Agent WebSocket is not connected."
            );
        }

        string json =
            JsonSerializer.Serialize(message);

        byte[] data =
            Encoding.UTF8.GetBytes(json);

        await _writeLock.WaitAsync(
            cancellationToken
        );

        try
        {
            Console.WriteLine(
                $"[IPC] UI -> Agent SEND: " +
                $"{GetMessageType(message)}, " +
                $"bytes={data.Length}"
            );

            await socket.SendAsync(
                new ArraySegment<byte>(data),
                WebSocketMessageType.Text,
                endOfMessage: true,
                cancellationToken
            );

            Console.WriteLine(
                "[IPC] UI -> Agent SENT"
            );
        }
        catch (Exception error)
        {
            Console.WriteLine(
                $"[IPC] UI -> Agent WRITE FAILED: {error}"
            );

            throw;
        }
        finally
        {
            _writeLock.Release();
        }
    }

    public async Task<JsonDocument?> ReceiveAsync(
        CancellationToken cancellationToken = default)
    {
        var socket = _socket;

        if (socket is null ||
            socket.State != WebSocketState.Open)
        {
            throw new InvalidOperationException(
                "Agent -> UI WebSocket is not connected."
            );
        }

        await _receiveLock.WaitAsync(
            cancellationToken
        );

        try
        {
            byte[] buffer = new byte[65536];

            using var messageBuffer =
                new MemoryStream();

            Console.WriteLine(
                "[IPC] Agent -> UI RECEIVE: waiting..."
            );

            while (true)
            {
                WebSocketReceiveResult result =
                    await socket.ReceiveAsync(
                        new ArraySegment<byte>(buffer),
                        cancellationToken
                    );

                if (result.MessageType ==
                    WebSocketMessageType.Close)
                {
                    Console.WriteLine(
                        "[IPC] Agent -> UI: WebSocket closed"
                    );

                    return null;
                }

                if (result.MessageType !=
                    WebSocketMessageType.Text)
                {
                    Console.WriteLine(
                        $"[IPC] Agent -> UI: ignoring " +
                        $"message type {result.MessageType}"
                    );

                    if (result.EndOfMessage)
                        return null;

                    continue;
                }

                if (result.Count > 0)
                {
                    messageBuffer.Write(
                        buffer,
                        0,
                        result.Count
                    );
                }

                Console.WriteLine(
                    $"[IPC] Agent -> UI RECEIVE: " +
                    $"chunk={result.Count}, " +
                    $"end={result.EndOfMessage}"
                );

                if (result.EndOfMessage)
                    break;
            }

            string json =
                Encoding.UTF8.GetString(
                    messageBuffer.ToArray()
                );

            using JsonDocument parsed =
                JsonDocument.Parse(json);

            string? type = null;

            if (
                parsed.RootElement.ValueKind ==
                    JsonValueKind.Object
                &&
                parsed.RootElement.TryGetProperty(
                    "type",
                    out JsonElement typeElement
                )
            )
            {
                type = typeElement.GetString();
            }

            int messageLength =
                checked((int)messageBuffer.Length);

            Console.WriteLine(
                $"[IPC] Agent -> UI RECEIVED: " +
                $"{type ?? "<no type>"}, " +
                $"bytes={messageLength}"
            );

            return JsonDocument.Parse(
                parsed.RootElement.GetRawText()
            );
        }
        finally
        {
            _receiveLock.Release();
        }
    }

    public async Task ReceiveLoopAsync(
        Func<JsonDocument, Task> onMessage,
        CancellationToken cancellationToken = default)
    {
        Console.WriteLine(
            "[IPC] Agent -> UI receive loop STARTED"
        );

        while (!cancellationToken.IsCancellationRequested)
        {
            try
            {
                JsonDocument? message =
                    await ReceiveAsync(
                        cancellationToken
                    );

                if (message is null)
                    break;

                try
                {
                    await onMessage(message);
                }
                finally
                {
                    message.Dispose();
                }
            }
            catch (OperationCanceledException)
                when (cancellationToken.IsCancellationRequested)
            {
                break;
            }
            catch (Exception error)
            {
                Console.WriteLine(
                    $"[IPC] Agent -> UI receive loop ERROR: {error}"
                );

                throw;
            }
        }

        Console.WriteLine(
            "[IPC] Agent -> UI receive loop STOPPED"
        );
    }

    public async Task DisconnectAsync()
    {
        var socket = _socket;

        if (socket is null)
            return;

        try
        {
            if (socket.State == WebSocketState.Open ||
                socket.State == WebSocketState.CloseReceived)
            {
                using var timeout =
                    new CancellationTokenSource(
                        TimeSpan.FromSeconds(2)
                    );

                await socket.CloseAsync(
                    WebSocketCloseStatus.NormalClosure,
                    "UI disconnecting",
                    timeout.Token
                );
            }
        }
        catch (Exception error)
        {
            Console.WriteLine(
                $"[IPC] WebSocket close failed: {error}"
            );
        }
        finally
        {
            if (ReferenceEquals(_socket, socket))
                _socket = null;

            socket.Dispose();
        }

        Console.WriteLine(
            "[IPC] UI <-> Agent WebSocket DISCONNECTED"
        );
    }

    private static string GetMessageType(
        object message)
    {
        try
        {
            using JsonDocument document =
                JsonDocument.Parse(
                    JsonSerializer.Serialize(message)
                );

            if (
                document.RootElement.TryGetProperty(
                    "type",
                    out JsonElement type
                )
            )
            {
                return type.GetString()
                    ?? "<no type>";
            }
        }
        catch
        {
            // Diagnostics must never break IPC.
        }

        return "<unknown>";
    }

    private void DisposeSocketOnly()
    {
        try
        {
            _socket?.Dispose();
        }
        catch
        {
        }

        _socket = null;
    }

    public void Dispose()
    {
        DisposeSocketOnly();
        _writeLock.Dispose();
        _receiveLock.Dispose();
    }
}