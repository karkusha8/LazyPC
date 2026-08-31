using Windows.UI;
using LazyPC.UI.Ipc;
using Microsoft.UI;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Imaging;
using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using Windows.Graphics;

namespace LazyPC.UI
{
    public sealed partial class MainWindow : Window
    {
        private readonly WsClient _ipcClient = new();
        private readonly CancellationTokenSource _ipcCancellation = new();

        private Task? _ipcReceiveTask;

        private readonly object _pairingResponseLock = new();
        private TaskCompletionSource<JsonDocument>? _pairingResponseSource;

        // Connection approval and QR pairing are completely independent UI flows.
        // Connection requests use their own Window; QR uses a ContentDialog.
        private Window? _connectionRequestWindow;
        private readonly object _connectionRequestLock = new();
        private TaskCompletionSource<bool>? _connectionRequestResultSource;

        private int _connectionRequestActive;
        private int _pairingDialogActive;

        [DllImport("user32.dll")]
        private static extern bool SetForegroundWindow(IntPtr hWnd);

        // =========================================================
        // UI THEME
        // =========================================================

        private static readonly Color LazyPcPurple =
            ColorHelper.FromArgb(0xFF, 0x72, 0x4B, 0xC7);

        private static readonly Color LazyPcPurpleDark =
            ColorHelper.FromArgb(0xFF, 0x5E, 0x3C, 0xA8);

        private static readonly Color LazyPcPurpleLight =
            ColorHelper.FromArgb(0xFF, 0xF1, 0xEB, 0xFA);

        private static readonly Color LazyPcText =
            ColorHelper.FromArgb(0xFF, 0x22, 0x1F, 0x26);

        private static readonly Color LazyPcWhite =
            ColorHelper.FromArgb(0xFF, 0xFF, 0xFF, 0xFF);

        public MainWindow()
        {
            this.InitializeComponent();

            ApplyLazyPcLightTheme();

            _ = InitializeIpcAsync();

            this.Closed += MainWindow_Closed;
        }

        private void ApplyLazyPcLightTheme()
        {
            if (Content is FrameworkElement root)
            {
                root.RequestedTheme = ElementTheme.Light;

                // Keep the application surface clean and light.
                if (root is Panel panel)
                {
                    panel.Background =
                        new SolidColorBrush(LazyPcWhite);
                }

                // Button appearance is controlled by the XAML styles.
                // Do not overwrite button colors here.
            }

            // Button styles are controlled by XAML.
        }

        // =========================================================
        // IPC
        // =========================================================

        private async Task InitializeIpcAsync()
        {
            try
            {
                await _ipcClient.ConnectAsync(
                    _ipcCancellation.Token
                );

                System.Diagnostics.Debug.WriteLine(
                    "[IPC] Connected to Agent"
                );

                // IMPORTANT:
                // Start the IPC reader BEFORE sending get_pc_info.
                //
                // The Agent can send unsolicited messages at any time
                // (connection_request, pairing_qr, etc.).  The reader
                // must therefore exist for the entire lifetime of the
                // pipe and must never depend on a UI button or a pending
                // request/response operation.
                //
                // There must be exactly ONE reader for the pipe.
                _ipcReceiveTask = ReceiveIpcLoopAsync();

                System.Diagnostics.Debug.WriteLine(
                    "[IPC] Permanent receive loop STARTED"
                );

                // This is only a normal request/response message.
                // It is deliberately sent AFTER the permanent reader
                // has started.
                await _ipcClient.SendAsync(
                    new
                    {
                        type = "get_pc_info"
                    },
                    _ipcCancellation.Token
                );

                System.Diagnostics.Debug.WriteLine(
                    "[IPC] get_pc_info SENT"
                );

                // The UI does not persist Trusted Device state.
                // Always request the current registry from the Agent when
                // the UI starts. The Agent is the only component that reads
                // the SQLite database.
                await _ipcClient.SendAsync(
                    new
                    {
                        type = "get_trusted_devices"
                    },
                    _ipcCancellation.Token
                );

                System.Diagnostics.Debug.WriteLine(
                    "[IPC] get_trusted_devices SENT"
                );
            }
            catch (OperationCanceledException)
            {
                // Window is closing.
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine(
                    $"[IPC] Connection failed: {ex.Message}"
                );
            }
        }

        private async Task ReceiveIpcLoopAsync()
        {
            try
            {
                while (!_ipcCancellation.IsCancellationRequested)
                {
                    System.Diagnostics.Debug.WriteLine(
                        "[IPC] Receive loop: WAITING FOR NEXT MESSAGE"
                    );

                    var message =
                        await _ipcClient.ReceiveAsync(
                            _ipcCancellation.Token
                        );

                    if (message is null)
                    {
                        System.Diagnostics.Debug.WriteLine(
                            "[IPC] Receive loop: WebSocket closed"
                        );
                        break;
                    }

                    System.Diagnostics.Debug.WriteLine(
                        "[IPC] Receive loop: MESSAGE ARRIVED"
                    );

                    if (!message.RootElement.TryGetProperty(
                            "type",
                            out var typeProperty))
                    {
                        continue;
                    }

                    string? type =
                        typeProperty.GetString();

                    if (type == "pc_info")
                    {
                        var root = message.RootElement;

                        string pcCode =
                            root.TryGetProperty(
                                "pc_code",
                                out var codeProperty)
                            ? codeProperty.GetString()
                                ?? string.Empty
                            : string.Empty;

                        if (
                            pcCode.Length == 9 &&
                            long.TryParse(
                                pcCode,
                                out _
                            )
                        )
                        {
                            string formatted =
                                $"{pcCode[..3]} " +
                                $"{pcCode[3..6]} " +
                                $"{pcCode[6..]}";

                            DispatcherQueue.TryEnqueue(
                                () =>
                                {
                                    PcCodeText.Text =
                                        formatted;
                                }
                            );
                        }

                        continue;
                    }

                    if (type == "trusted_devices")
                    {
                        // Detach the payload from the receive iteration so the
                        // UI thread can safely process it asynchronously.
                        string rawTrustedDevices =
                            message.RootElement.GetRawText();

                        bool queued = DispatcherQueue.TryEnqueue(
                            () =>
                            {
                                try
                                {
                                    using JsonDocument trustedMessage =
                                        JsonDocument.Parse(rawTrustedDevices);

                                    RenderTrustedDevices(
                                        trustedMessage.RootElement
                                    );
                                }
                                catch (Exception ex)
                                {
                                    Log(
                                        $"[IPC] trusted_devices dispatch failed: {ex}"
                                    );
                                }
                            }
                        );

                        if (!queued)
                        {
                            Log(
                                "[IPC] ERROR: DispatcherQueue.TryEnqueue failed for trusted_devices"
                            );
                        }

                        continue;
                    }

                    if (type == "connection_request")
                    {
                        System.Diagnostics.Debug.WriteLine(
                            "[IPC] connection_request RECEIVED -> dispatching to UI"
                        );

                        // Detach the JSON payload from the receive iteration.
                        // The IPC reader remains completely independent from
                        // the lifetime of the connection-request window.
                        string rawMessage =
                            message.RootElement.GetRawText();

                        bool queued = DispatcherQueue.TryEnqueue(
                            () =>
                            {
                                try
                                {
                                    Log(
                                        "[IPC] connection_request DISPATCHED -> showing dialog"
                                    );

                                    using JsonDocument request =
                                        JsonDocument.Parse(rawMessage);

                                    _ = HandleConnectionRequestAsync(
                                        request
                                    );
                                }
                                catch (Exception ex)
                                {
                                    Log(
                                        $"[IPC] connection_request dispatch failed: {ex}"
                                    );
                                }
                            }
                        );

                        if (!queued)
                        {
                            System.Diagnostics.Debug.WriteLine(
                                "[IPC] ERROR: DispatcherQueue.TryEnqueue failed for connection_request"
                            );
                        }

                        continue;
                    }

                    if (type == "pairing_qr")
                    {
                        TaskCompletionSource<JsonDocument>?
                            source;

                        lock (_pairingResponseLock)
                        {
                            source =
                                _pairingResponseSource;

                            _pairingResponseSource =
                                null;
                        }

                        source?.TrySetResult(
                            message
                        );

                        continue;
                    }

                    if (type == "ordinary_auth_secret")
                    {
                        string secret =
                            message.RootElement.TryGetProperty(
                                "secret",
                                out var secretProperty)
                                ? secretProperty.GetString()
                                    ?? string.Empty
                                : string.Empty;

                        string sessionId =
                            message.RootElement.TryGetProperty(
                                "session_id",
                                out var sessionProperty)
                                ? sessionProperty.GetString()
                                    ?? string.Empty
                                : string.Empty;

                        if (
                            secret.Length == 9 &&
                            long.TryParse(secret, out _)
                        )
                        {
                            Log(
                                "[IPC] ordinary_auth_secret RECEIVED"
                            );

                            DispatcherQueue.TryEnqueue(
                                () =>
                                {
                                    Log(
                                        "[IPC] ordinary_auth_secret DISPATCHED -> showing secret"
                                    );

                                    _ = ShowOrdinaryAuthSecretAsync(
                                        secret,
                                        sessionId
                                    );
                                }
                            );
                        }
                        else
                        {
                            Log(
                                "[IPC] Invalid ordinary_auth_secret received"
                            );
                        }

                        continue;
                    }

                    System.Diagnostics.Debug.WriteLine(
                        $"[IPC] Unhandled event: {type}"
                    );
                }
            }
            catch (OperationCanceledException)
            {
                // Window is closing.
            }
            catch (ObjectDisposedException)
            {
                // Window is closing.
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine(
                    $"[IPC] Receive loop FAILED: {ex}"
                );
            }
            finally
            {
                System.Diagnostics.Debug.WriteLine(
                    "[IPC] Receive loop STOPPED"
                );
            }
        }

        private async Task HandleConnectionRequestAsync(
            JsonDocument message)
        {
            if (Interlocked.Exchange(
                    ref _connectionRequestActive,
                    1
                ) == 1)
            {
                Log(
                    "[UI] Duplicate connection_request ignored: another request is active"
                );

                return;
            }

            try
            {
                Log("[IPC] HandleConnectionRequestAsync START");

                var root = message.RootElement;

                string deviceId =
                    root.TryGetProperty(
                        "device_id",
                        out var deviceProperty)
                    ? deviceProperty.GetString()
                        ?? "Android"
                    : "Android";

                string connectionId =
                    root.TryGetProperty(
                        "connection_id",
                        out var connectionProperty)
                    ? connectionProperty.GetString()
                        ?? string.Empty
                    : string.Empty;

                var device = new Dictionary<string, string>();

                if (root.TryGetProperty("device", out var deviceInfoProperty))
                {
                    if (deviceInfoProperty.ValueKind == JsonValueKind.Object)
                    {
                        foreach (var propertyName in new[]
                        {
            "platform",
            "manufacturer",
            "model",
            "android_version"
        })
                        {
                            if (deviceInfoProperty.TryGetProperty(
                                    propertyName,
                                    out var valueProperty))
                            {
                                if (valueProperty.ValueKind == JsonValueKind.String)
                                {
                                    string? value = valueProperty.GetString();

                                    if (!string.IsNullOrWhiteSpace(value))
                                    {
                                        device[propertyName] = value.Trim();
                                    }
                                }
                            }
                        }
                    }
                    else if (deviceProperty.ValueKind == JsonValueKind.String)
                    {
                        // Старый формат: "device": "Android"
                        string? legacyPlatform = deviceProperty.GetString();

                        if (!string.IsNullOrWhiteSpace(legacyPlatform))
                        {
                            device["platform"] = legacyPlatform.Trim();
                        }
                    }
                }

                Log(
                    $"[UI] Preparing CONNECTION window: " +
                    $"device={deviceId}, connection={connectionId}"
                );

                bool accepted =
                    await ShowConnectionRequestWindowAsync(
                        deviceId,
                        connectionId,
                        device
                    );
                // The request window may have been the foreground window.
                // Restore the main LazyPC window before continuing the flow.
                if (accepted)
                {
                    Activate();

                    IntPtr mainHwnd =
                        WinRT.Interop.WindowNative.GetWindowHandle(this);

                    if (mainHwnd != IntPtr.Zero)
                    {
                        SetForegroundWindow(mainHwnd);
                    }

                    await Task.Delay(50);
                }

                Log(
                    $"[UI] CONNECTION window closed: accepted={accepted}"
                );

                Log(
                    $"[UI] Sending connection_response: " +
                    $"accepted={accepted}, connection={connectionId}"
                );

                await _ipcClient.SendAsync(
                    new
                    {
                        type = "connection_response",
                        accepted,
                        connection_id = connectionId,
                        device_id = deviceId
                    },
                    _ipcCancellation.Token
                );

                Log("[UI] connection_response sent");
            }
            catch (OperationCanceledException)
            {
                // Window is closing.
            }
            catch (Exception ex)
            {
                Log(
                    $"[IPC] Connection request failed: {ex}"
                );
            }
            finally
            {
                lock (_connectionRequestLock)
                {
                    _connectionRequestResultSource = null;
                }

                Volatile.Write(
                    ref _connectionRequestActive,
                    0
                );

                Log(
                    "[UI] CONNECTION request flow finished"
                );
            }
        }

        private async Task<bool> ShowConnectionRequestWindowAsync(
            string deviceId,
            string connectionId,
            Dictionary<string, string>? device)
        {
            var resultSource =
                new TaskCompletionSource<bool>(
                    TaskCreationOptions.RunContinuationsAsynchronously
                );

            lock (_connectionRequestLock)
            {
                if (_connectionRequestResultSource is not null)
                {
                    Log(
                        "[UI] Connection request window already exists"
                    );

                    return false;
                }

                _connectionRequestResultSource =
                    resultSource;
            }

            // ---------------------------------------------------------
            // LazyPC CONNECTION REQUEST UI
            // ---------------------------------------------------------

            var content = new Border
            {
                Background =
                    new SolidColorBrush(LazyPcWhite),
                Padding =
                    new Thickness(32, 26, 32, 26),
                CornerRadius =
                    new CornerRadius(16)
            };

            var layout = new StackPanel
            {
                Spacing = 10,
                HorizontalAlignment =
                    HorizontalAlignment.Stretch
            };

            layout.Children.Add(
                new TextBlock
                {
                    Text = "LazyPC",
                    FontSize = 16,
                    FontWeight =
                        Microsoft.UI.Text.FontWeights.SemiBold,
                    Foreground =
                        new SolidColorBrush(LazyPcText),
                    HorizontalAlignment =
                        HorizontalAlignment.Center
                }
            );

            layout.Children.Add(
                new TextBlock
                {
                    Text = "Запрос на подключение",
                    FontSize = 24,
                    FontWeight =
                        Microsoft.UI.Text.FontWeights.SemiBold,
                    Foreground =
                        new SolidColorBrush(LazyPcText),
                    Margin =
                        new Thickness(0, 4, 0, 2),
                    HorizontalAlignment =
                        HorizontalAlignment.Center
                }
            );

            string platform =
                device?.GetValueOrDefault("platform", "Android")
                ?? "Android";

            string manufacturer =
                device?.GetValueOrDefault("manufacturer", "")
                ?? "";

            string model =
                device?.GetValueOrDefault("model", "")
                ?? "";

            string androidVersion =
                device?.GetValueOrDefault("android_version", "")
                ?? "";

            string deviceName =
                string.IsNullOrWhiteSpace(manufacturer)
                    ? model
                    : string.IsNullOrWhiteSpace(model)
                        ? manufacturer
                        : $"{manufacturer} {model}";

            if (string.IsNullOrWhiteSpace(deviceName))
            {
                deviceName = $"Device {deviceId}";
            }

            layout.Children.Add(
                new TextBlock
                {
                    Text = deviceName,
                    FontSize = 20,
                    FontWeight =
                        Microsoft.UI.Text.FontWeights.SemiBold,
                    Foreground =
                        new SolidColorBrush(LazyPcPurpleDark),
                    HorizontalAlignment =
                        HorizontalAlignment.Center,
                    TextAlignment =
                        Microsoft.UI.Xaml.TextAlignment.Center
                }
            );

            string deviceDetails =
                string.IsNullOrWhiteSpace(androidVersion)
                    ? platform
                    : $"{platform} • Android {androidVersion}";

            layout.Children.Add(
                new TextBlock
                {
                    Text = deviceDetails,
                    FontSize = 14,
                    Foreground =
                        new SolidColorBrush(LazyPcText),
                    Opacity = 0.60,
                    HorizontalAlignment =
                        HorizontalAlignment.Center,
                    TextAlignment =
                        Microsoft.UI.Xaml.TextAlignment.Center
                }
            );

            layout.Children.Add(
                new TextBlock
                {
                    Text = "хочет подключиться к этому компьютеру",
                    FontSize = 14,
                    Foreground =
                        new SolidColorBrush(LazyPcText),
                    Opacity = 0.72,
                    Margin =
                        new Thickness(0, 8, 0, 14),
                    HorizontalAlignment =
                        HorizontalAlignment.Center,
                    TextAlignment =
                        Microsoft.UI.Xaml.TextAlignment.Center
                }
            );

            var buttons = new StackPanel
            {
                Orientation =
                    Orientation.Vertical,
                HorizontalAlignment =
                    HorizontalAlignment.Center,
                Spacing = 10
            };

            // Accept: white button with a thin LazyPC-purple border.
            // Hover: fully purple with white text.
            var acceptNormalBrush =
                new SolidColorBrush(LazyPcWhite);

            var acceptBorderBrush =
                new SolidColorBrush(LazyPcPurple);

            var acceptHoverBrush =
                new SolidColorBrush(LazyPcPurple);

            // Decline: white with dark text.
            // Hover: red with white text.
            var declineNormalBrush =
                new SolidColorBrush(LazyPcWhite);

            var declineHoverBrush =
                new SolidColorBrush(
                    ColorHelper.FromArgb(
                        0xFF,
                        0xDC,
                        0x35,
                        0x45
                    )
                );

            var acceptButton = new Button
            {
                Content = "Принять",
                Width = 280,
                Height = 44,
                IsEnabled = true,
                Opacity = 1.0,
                Background = acceptNormalBrush,
                Foreground =
                    new SolidColorBrush(LazyPcPurple),
                BorderBrush =
                    acceptBorderBrush,
                BorderThickness =
                    new Thickness(1),
                CornerRadius =
                    new CornerRadius(10),
                Padding =
                    new Thickness(18, 0, 18, 0)
            };

            var declineButton = new Button
            {
                Content = "Отклонить",
                Width = 280,
                Height = 44,
                IsEnabled = true,
                Opacity = 1.0,
                Background = declineNormalBrush,
                Foreground =
                    new SolidColorBrush(LazyPcText),
                BorderBrush =
                    new SolidColorBrush(
                        ColorHelper.FromArgb(
                            0xFF,
                            0xDD,
                            0xDD,
                            0xDD
                        )
                    ),
                BorderThickness =
                    new Thickness(1),
                CornerRadius =
                    new CornerRadius(10),
                Padding =
                    new Thickness(18, 0, 18, 0)
            };

            // Force the WinUI Button template to use our hover colors.
            acceptButton.Resources["ButtonBackgroundPointerOver"] =
                acceptHoverBrush;
            acceptButton.Resources["ButtonBorderBrushPointerOver"] =
                acceptHoverBrush;
            acceptButton.Resources["ButtonForegroundPointerOver"] =
                new SolidColorBrush(LazyPcWhite);
            acceptButton.Resources["ButtonBackgroundPressed"] =
                acceptHoverBrush;
            acceptButton.Resources["ButtonBorderBrushPressed"] =
                acceptHoverBrush;
            acceptButton.Resources["ButtonForegroundPressed"] =
                new SolidColorBrush(LazyPcWhite);

            declineButton.Resources["ButtonBackgroundPointerOver"] =
                declineHoverBrush;
            declineButton.Resources["ButtonBorderBrushPointerOver"] =
                declineHoverBrush;
            declineButton.Resources["ButtonForegroundPointerOver"] =
                new SolidColorBrush(LazyPcWhite);
            declineButton.Resources["ButtonBackgroundPressed"] =
                declineHoverBrush;
            declineButton.Resources["ButtonBorderBrushPressed"] =
                declineHoverBrush;
            declineButton.Resources["ButtonForegroundPressed"] =
                new SolidColorBrush(LazyPcWhite);

            acceptButton.PointerEntered += (_, _) =>
            {
                acceptButton.Background = acceptHoverBrush;
                acceptButton.Foreground =
                    new SolidColorBrush(LazyPcWhite);
                acceptButton.BorderBrush = acceptHoverBrush;
            };

            acceptButton.PointerExited += (_, _) =>
            {
                acceptButton.Background = acceptNormalBrush;
                acceptButton.Foreground =
                    new SolidColorBrush(LazyPcPurple);
                acceptButton.BorderBrush = acceptBorderBrush;
            };

            declineButton.PointerEntered += (_, _) =>
            {
                declineButton.Background = declineHoverBrush;
                declineButton.Foreground =
                    new SolidColorBrush(LazyPcWhite);
                declineButton.BorderBrush = declineHoverBrush;
            };

            declineButton.PointerExited += (_, _) =>
            {
                declineButton.Background = declineNormalBrush;
                declineButton.Foreground =
                    new SolidColorBrush(LazyPcText);
                declineButton.BorderBrush =
                    new SolidColorBrush(
                        ColorHelper.FromArgb(
                            0xFF,
                            0xDD,
                            0xDD,
                            0xDD
                        )
                    );
            };

            buttons.Children.Add(acceptButton);
            buttons.Children.Add(declineButton);

            layout.Children.Add(buttons);

            content.Child = layout;

            var window = new Window
            {
                Title = "LazyPC — Connection request",
                Content = content
            };

            _connectionRequestWindow = window;

            bool resultAlreadySet = false;

            void Complete(bool accepted)
            {
                if (resultAlreadySet)
                    return;

                resultAlreadySet = true;
                resultSource.TrySetResult(accepted);

                try
                {
                    window.Close();
                }
                catch
                {
                    // Window may already be closing.
                }
            }

            acceptButton.Click += (_, _) =>
            {
                Log("[UI] Connection request: ACCEPT clicked");
                Complete(true);
            };

            declineButton.Click += (_, _) =>
            {
                Log("[UI] Connection request: DECLINE clicked");
                Complete(false);
            };

            window.Closed += (_, _) =>
            {
                if (!resultAlreadySet)
                {
                    Log(
                        "[UI] Connection request window closed " +
                        "without explicit decision -> DECLINE"
                    );

                    resultAlreadySet = true;
                    resultSource.TrySetResult(false);
                }

                lock (_connectionRequestLock)
                {
                    if (ReferenceEquals(
                            _connectionRequestResultSource,
                            resultSource))
                    {
                        _connectionRequestResultSource = null;
                    }
                }

                if (ReferenceEquals(
                        _connectionRequestWindow,
                        window))
                {
                    _connectionRequestWindow = null;
                }
            };

            try
            {
                // WinUI 3 Window has no XAML Width/Height properties.
                // Resize the native AppWindow after creation.
                IntPtr requestHwnd =
                    WinRT.Interop.WindowNative.GetWindowHandle(
                        window
                    );

                if (requestHwnd != IntPtr.Zero)
                {
                    WindowId requestWindowId =
                        Win32Interop.GetWindowIdFromWindow(
                            requestHwnd
                        );

                    AppWindow? appWindow =
                        AppWindow.GetFromWindowId(
                            requestWindowId
                        );

                    appWindow?.Resize(
                        new SizeInt32(
                            500,
                            440
                        )
                    );

                    // Center the request window over the main LazyPC window.
                    IntPtr mainHwnd =
                        WinRT.Interop.WindowNative.GetWindowHandle(
                            this
                        );

                    if (
                        mainHwnd != IntPtr.Zero &&
                        appWindow is not null)
                    {
                        WindowId mainWindowId =
                            Win32Interop.GetWindowIdFromWindow(
                                mainHwnd
                            );

                        AppWindow? mainAppWindow =
                            AppWindow.GetFromWindowId(
                                mainWindowId
                            );

                        if (mainAppWindow is not null)
                        {
                            PointInt32 mainPosition =
                                mainAppWindow.Position;

                            SizeInt32 mainSize =
                                mainAppWindow.Size;

                            SizeInt32 requestSize =
                                appWindow.Size;

                            int x =
                                mainPosition.X +
                                (mainSize.Width -
                                 requestSize.Width) / 2;

                            int y =
                                mainPosition.Y +
                                (mainSize.Height -
                                 requestSize.Height) / 2;

                            appWindow.Move(
                                new PointInt32(x, y)
                            );
                        }
                    }
                }

                window.Activate();

                requestHwnd =
                    WinRT.Interop.WindowNative.GetWindowHandle(
                        window
                    );

                if (requestHwnd != IntPtr.Zero)
                {
                    SetForegroundWindow(requestHwnd);

                    Log(
                        $"[UI] CONNECTION window activated and centered: " +
                        $"hwnd=0x{requestHwnd.ToInt64():X}"
                    );
                }

                Log(
                    "[UI] Styled CONNECTION request window shown"
                );

                return await resultSource.Task.WaitAsync(
                    _ipcCancellation.Token
                );
            }
            finally
            {
                if (!resultSource.Task.IsCompleted)
                {
                    resultSource.TrySetResult(false);
                }

                if (ReferenceEquals(
                        _connectionRequestWindow,
                        window))
                {
                    _connectionRequestWindow = null;
                }
            }
        }

        private void MainWindow_Closed(
            object sender,
            WindowEventArgs args)
        {
            _ipcCancellation.Cancel();

            lock (_pairingResponseLock)
            {
                _pairingResponseSource?.TrySetCanceled();

                _pairingResponseSource =
                    null;
            }

            lock (_connectionRequestLock)
            {
                _connectionRequestResultSource?.TrySetCanceled();
                _connectionRequestResultSource = null;
            }

            try
            {
                _connectionRequestWindow?.Close();
            }
            catch
            {
                // Window may already be closed.
            }

            _connectionRequestWindow = null;

            _ipcClient.Dispose();
            _ipcCancellation.Dispose();
        }

        // =========================================================
        // TRUSTED PAIRING
        // =========================================================

        /// <summary>
        /// Temporary UI test for the connection-request dialog.
        ///
        /// This does not start a real WebRTC connection. It only verifies
        /// that the Windows UI can display the same request that will later
        /// arrive from the Agent through IPC.
        /// </summary>
        private async void TestConnectionRequest_Click(
            object sender,
            RoutedEventArgs e)
        {
            try
            {
                using var message = JsonDocument.Parse(
                    """
                    {
                        "type": "connection_request",
                        "device_id": "742 381 529",
                        "connection_id": "test-connection"
                    }
                    """
                );

                await HandleConnectionRequestAsync(message);
            }
            catch (OperationCanceledException)
            {
                // Window is closing.
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine(
                    $"[TEST] Connection request failed: {ex}"
                );

                await ShowErrorAsync(
                    $"Test request failed:\n{ex.Message}"
                );
            }
        }

        private async void PairNewDevice_Click(
            object sender,
            RoutedEventArgs e)
        {
            // IMPORTANT: do not queue QR behind a connection approval dialog.
            // The previous implementation did exactly that, which made the QR
            // appear immediately after Accept and made it look as if both
            // dialogs belonged to one connection flow.
            if (Volatile.Read(ref _connectionRequestActive) == 1)
            {
                Log("[UI] Pair new device ignored: CONNECTION dialog is active");
                return;
            }

            if (Interlocked.Exchange(ref _pairingDialogActive, 1) == 1)
            {
                Log("[UI] Pair new device ignored: QR pairing is already active");
                return;
            }

            try
            {
                Log("[PAIRING] User clicked Pair new device");

                var responseSource =
                    new TaskCompletionSource<JsonDocument>(
                        TaskCreationOptions.RunContinuationsAsynchronously
                    );

                lock (_pairingResponseLock)
                {
                    if (_pairingResponseSource is not null)
                    {
                        Log("[PAIRING] Existing pairing IPC request detected; aborting new request");
                        return;
                    }

                    _pairingResponseSource = responseSource;
                }

                Log("[PAIRING] Sending pairing_start to Agent");

                await _ipcClient.SendAsync(
                    new
                    {
                        type = "pairing_start"
                    },
                    _ipcCancellation.Token
                );

                Log("[PAIRING] Waiting for pairing_qr from Agent");

                var response =
                    await responseSource.Task.WaitAsync(
                        TimeSpan.FromSeconds(15),
                        _ipcCancellation.Token
                    );

                var root = response.RootElement;

                string? type =
                    root.TryGetProperty("type", out var typeProperty)
                        ? typeProperty.GetString()
                        : null;

                Log($"[PAIRING] Agent response: {type ?? "<no type>"}");

                if (type != "pairing_qr")
                {
                    await ShowErrorAsync(
                        "Unexpected response from LazyPC Agent."
                    );
                    return;
                }

                bool success =
                    root.TryGetProperty(
                        "success",
                        out var successProperty
                    ) && successProperty.GetBoolean();

                if (!success)
                {
                    string error = "Pairing could not be started.";

                    if (root.TryGetProperty(
                            "error",
                            out var errorProperty))
                    {
                        error =
                            errorProperty.GetString() ?? error;
                    }

                    Log($"[PAIRING] Agent rejected pairing: {error}");
                    await ShowErrorAsync(error);
                    return;
                }

                if (!root.TryGetProperty(
                        "path",
                        out var pathProperty))
                {
                    await ShowErrorAsync(
                        "Agent did not provide a QR image."
                    );
                    return;
                }

                string? qrPath = pathProperty.GetString();

                if (string.IsNullOrWhiteSpace(qrPath))
                {
                    await ShowErrorAsync("QR image path is empty.");
                    return;
                }

                Log($"[PAIRING] Showing QR dialog: {qrPath}");
                await ShowPairingQrAsync(qrPath);
                Log("[PAIRING] QR dialog finished");
            }
            catch (TimeoutException)
            {
                Log("[PAIRING] Agent did not respond within 15 seconds");
                await ShowErrorAsync(
                    "The Agent did not respond in time."
                );
            }
            catch (OperationCanceledException)
            {
                Log("[PAIRING] Pairing cancelled because UI is closing");
            }
            catch (Exception ex)
            {
                Log($"[PAIRING] Pairing failed: {ex}");
                await ShowErrorAsync(
                    $"Could not start pairing:\n{ex.Message}"
                );
            }
            finally
            {
                lock (_pairingResponseLock)
                {
                    _pairingResponseSource = null;
                }

                Volatile.Write(ref _pairingDialogActive, 0);
                Log("[PAIRING] Pairing flow finished");
            }
        }

        // =========================================================
        // PAIRING QR DIALOG
        // =========================================================

        private async Task ShowPairingQrAsync(
            string qrPath)
        {
            if (!File.Exists(qrPath))
            {
                await ShowErrorAsync(
                    "The Agent created the QR, but the image file was not found."
                );

                return;
            }

            var qrImage = new Image
            {
                Width = 220,
                Height = 220,
                Stretch =
                    Microsoft.UI.Xaml.Media.Stretch.Uniform
            };

            var bitmap =
                new BitmapImage();

            using (var stream =
                   File.OpenRead(qrPath))
            {
                await bitmap.SetSourceAsync(
                    stream.AsRandomAccessStream()
                );
            }

            qrImage.Source = bitmap;

            var content = new StackPanel
            {
                Spacing = 18,
                HorizontalAlignment =
                    HorizontalAlignment.Center
            };

            content.Children.Add(
                new TextBlock
                {
                    Text =
                        "Scan this QR code",
                    FontSize = 20,
                    HorizontalAlignment =
                        HorizontalAlignment.Center
                }
            );

            content.Children.Add(
                qrImage
            );

            content.Children.Add(
                new TextBlock
                {
                    Text =
                        "Use LazyPC on your Android device\n" +
                        "to scan and pair this PC.",
                    FontSize = 14,
                    Opacity = 0.65,
                    TextAlignment =
                        Microsoft.UI.Xaml.TextAlignment.Center,
                    HorizontalAlignment =
                        HorizontalAlignment.Center
                }
            );

            content.Children.Add(
                new TextBlock
                {
                    Text =
                        "This code can be used once.",
                    FontSize = 13,
                    Opacity = 0.5,
                    HorizontalAlignment =
                        HorizontalAlignment.Center
                }
            );

            var dialog = new ContentDialog
            {
                Title =
                    "Pair new device",

                Content =
                    content,

                CloseButtonText =
                    "Cancel"
            };

            var root = Content?.XamlRoot;

            if (root is null)
            {
                throw new InvalidOperationException(
                    "MainWindow XamlRoot is not available."
                );
            }

            dialog.XamlRoot = root;

            try
            {
                Activate();

                IntPtr hwnd =
                    WinRT.Interop.WindowNative.GetWindowHandle(
                        this
                    );

                if (hwnd != IntPtr.Zero)
                {
                    SetForegroundWindow(hwnd);
                }

                Log("[UI] SHOW QR dialog");

                await dialog.ShowAsync();

                Log("[UI] HIDE QR dialog");
            }
            catch (Exception ex)
            {
                Log($"[UI] QR dialog failed: {ex}");
                throw;
            }
        }

        // =========================================================
        // ORDINARY V2 AUTH SECRET
        // =========================================================

        private async Task ShowOrdinaryAuthSecretAsync(
            string secret,
            string sessionId)
        {
            if (
                secret.Length != 9 ||
                !long.TryParse(secret, out _)
            )
            {
                Log(
                    "[UI] Refusing to display invalid Ordinary V2 secret"
                );
                return;
            }

            string formatted =
                $"{secret[..3]} " +
                $"{secret[3..6]} " +
                $"{secret[6..]}";

            var codeText = new TextBlock
            {
                Text = formatted,
                FontSize = 42,
                FontWeight =
                    Microsoft.UI.Text.FontWeights.SemiBold,
                Foreground =
                    new SolidColorBrush(LazyPcPurpleDark),
                HorizontalAlignment =
                    HorizontalAlignment.Center,
                TextAlignment =
                    Microsoft.UI.Xaml.TextAlignment.Center
            };

            var content = new StackPanel
            {
                Width = 390,
                Spacing = 14,
                Padding = new Thickness(10, 4, 10, 4),
                HorizontalAlignment =
                    HorizontalAlignment.Center
            };

            content.Children.Add(
                new TextBlock
                {
                    Text = "Код подключения",
                    FontSize = 24,
                    FontWeight =
                        Microsoft.UI.Text.FontWeights.SemiBold,
                    Foreground =
                        new SolidColorBrush(LazyPcText),
                    HorizontalAlignment =
                        HorizontalAlignment.Center,
                    TextAlignment =
                        Microsoft.UI.Xaml.TextAlignment.Center
                }
            );

            content.Children.Add(
                new TextBlock
                {
                    Text =
                        "Введите этот одноразовый код" +
                        "на Android-устройстве.",
                    FontSize = 15,
                    Foreground =
                        new SolidColorBrush(LazyPcText),
                    Opacity = 0.70,
                    TextAlignment =
                        Microsoft.UI.Xaml.TextAlignment.Center,
                    HorizontalAlignment =
                        HorizontalAlignment.Center
                }
            );

            var codeBorder = new Border
            {
                Background =
                    new SolidColorBrush(LazyPcPurpleLight),
                BorderBrush =
                    new SolidColorBrush(
                        ColorHelper.FromArgb(
                            0x35,
                            0x72,
                            0x4B,
                            0xC7
                        )
                    ),
                BorderThickness =
                    new Thickness(1),
                Padding =
                    new Thickness(28, 18, 28, 18),
                CornerRadius =
                    new CornerRadius(14),
                HorizontalAlignment =
                    HorizontalAlignment.Center,
                Child = codeText
            };

            content.Children.Add(codeBorder);

            content.Children.Add(
                new TextBlock
                {
                    Text =
                        "Код действует только для текущего " +
                        "подключения.",
                    FontSize = 13,
                    Foreground =
                        new SolidColorBrush(LazyPcText),
                    Opacity = 0.55,
                    TextAlignment =
                        Microsoft.UI.Xaml.TextAlignment.Center,
                    HorizontalAlignment =
                        HorizontalAlignment.Center
                }
            );

            if (!string.IsNullOrWhiteSpace(sessionId))
            {
                Log(
                    $"[UI] Showing Ordinary V2 secret for session={sessionId}"
                );
            }

            var dialog = new ContentDialog
            {
                Title = "LazyPC",
                Content = content,
                CloseButtonText = "Закрыть"
            };

            var root = Content?.XamlRoot;

            if (root is null)
            {
                Log(
                    "[UI] Cannot show Ordinary V2 secret: XamlRoot is null"
                );
                return;
            }

            dialog.XamlRoot = root;

            try
            {
                Activate();

                IntPtr hwnd =
                    WinRT.Interop.WindowNative.GetWindowHandle(
                        this
                    );

                if (hwnd != IntPtr.Zero)
                {
                    SetForegroundWindow(hwnd);
                }

                Log(
                    "[UI] SHOW Ordinary V2 auth secret"
                );

                await dialog.ShowAsync();

                Log(
                    "[UI] HIDE Ordinary V2 auth secret"
                );
            }
            catch (Exception ex)
            {
                Log(
                    $"[UI] Ordinary V2 secret dialog failed: {ex}"
                );
            }
        }

        // =========================================================
        // TRUSTED DEVICES
        // =========================================================

        private void RenderTrustedDevices(
            JsonElement root)
        {
            if (!root.TryGetProperty(
                    "devices",
                    out var devicesProperty) ||
                devicesProperty.ValueKind != JsonValueKind.Array)
            {
                Log(
                    "[UI] trusted_devices received without a valid devices array"
                );
                return;
            }

            TrustedDevicesPanel.Children.Clear();

            int count = 0;

            foreach (var device in devicesProperty.EnumerateArray())
            {
                count++;

                string manufacturer = GetJsonString(
                    device,
                    "manufacturer"
                );

                string model = GetJsonString(
                    device,
                    "model"
                );

                string platform = GetJsonString(
                    device,
                    "platform"
                );

                string androidVersion = GetJsonString(
                    device,
                    "android_version"
                );

                string displayName = GetJsonString(
                    device,
                    "display_name"
                );

                string deviceName;

                if (!string.IsNullOrWhiteSpace(displayName))
                {
                    deviceName = displayName;
                }
                else if (
                    !string.IsNullOrWhiteSpace(manufacturer) &&
                    !string.IsNullOrWhiteSpace(model))
                {
                    deviceName = $"{manufacturer} {model}";
                }
                else if (!string.IsNullOrWhiteSpace(model))
                {
                    deviceName = model;
                }
                else if (!string.IsNullOrWhiteSpace(manufacturer))
                {
                    deviceName = manufacturer;
                }
                else
                {
                    deviceName = "Android устройство";
                }

                string details =
                    !string.IsNullOrWhiteSpace(androidVersion)
                        ? $"{platform} · Android {androidVersion}"
                        : platform;

                if (string.IsNullOrWhiteSpace(details))
                {
                    details = "Trusted Device";
                }

                var card = new Border
                {
                    Padding = new Thickness(18),
                    CornerRadius = new CornerRadius(16),
                    Background =
                        (Brush)((FrameworkElement)Content).Resources["CardBgSoft"],
                    BorderBrush =
                        (Brush)((FrameworkElement)Content).Resources["Border"],
                    BorderThickness = new Thickness(1),
                    Margin = new Thickness(0, 0, 0, 10)
                };

                var grid = new Grid();

                grid.ColumnDefinitions.Add(
                    new ColumnDefinition
                    {
                        Width = GridLength.Auto
                    }
                );

                grid.ColumnDefinitions.Add(
                    new ColumnDefinition
                    {
                        Width = new GridLength(1, GridUnitType.Star)
                    }
                );

                grid.ColumnDefinitions.Add(
                    new ColumnDefinition
                    {
                        Width = GridLength.Auto
                    }
                );

                var iconBorder = new Border
                {
                    Width = 46,
                    Height = 46,
                    CornerRadius = new CornerRadius(14),
                    Background =
                        (Brush)((FrameworkElement)Content).Resources["PurpleSoft"]
                };

                iconBorder.Child = new FontIcon
                {
                    Glyph = "\uE8EA",
                    FontSize = 22,
                    Foreground =
                        (Brush)((FrameworkElement)Content). Resources["PurpleDark"],
                    HorizontalAlignment =
                        HorizontalAlignment.Center,
                    VerticalAlignment =
                        VerticalAlignment.Center
                };

                Grid.SetColumn(iconBorder, 0);
                grid.Children.Add(iconBorder);

                var textPanel = new StackPanel
                {
                    Margin = new Thickness(14, 0, 14, 0),
                    VerticalAlignment =
                        VerticalAlignment.Center,
                    Spacing = 2
                };

                textPanel.Children.Add(
                    new TextBlock
                    {
                        Text = deviceName,
                        FontSize = 15,
                        FontWeight =
                            Microsoft.UI.Text.FontWeights.SemiBold,
                        Foreground =
                            (Brush)((FrameworkElement)Content).Resources["Text"]
                    }
                );

                textPanel.Children.Add(
                    new TextBlock
                    {
                        Text = details,
                        FontSize = 13,
                        Foreground =
                            (Brush)((FrameworkElement)Content).Resources["TextSecondary"]
                    }
                );

                Grid.SetColumn(textPanel, 1);
                grid.Children.Add(textPanel);

                var trustedBadge = new Border
                {
                    Padding = new Thickness(10, 5, 10, 5),
                    CornerRadius = new CornerRadius(8),
                    Background =
                        (Brush)((FrameworkElement)Content).Resources["PurpleSoft"],
                    VerticalAlignment =
                        VerticalAlignment.Center
                };

                trustedBadge.Child = new TextBlock
                {
                    Text = "Доверенное",
                    FontSize = 12,
                    Foreground =
                        (Brush)((FrameworkElement)Content).     Resources["PurpleDark"]
                };

                Grid.SetColumn(trustedBadge, 2);
                grid.Children.Add(trustedBadge);

                card.Child = grid;
                TrustedDevicesPanel.Children.Add(card);
            }

            if (count == 0)
            {
                var emptyCard = new Border
                {
                    Padding = new Thickness(18),
                    CornerRadius = new CornerRadius(16),
                    Background =
                        (Brush)((FrameworkElement)Content).Resources["CardBgSoft"],
                    BorderBrush =
                        (Brush)((FrameworkElement)Content).Resources["Border"],
                    BorderThickness = new Thickness(1)
                };

                emptyCard.Child = new TextBlock
                {
                    Text = "Нет доверенных устройств",
                    FontSize = 14,
                    Foreground =
                        (Brush)((FrameworkElement)Content). Resources["TextSecondary"],
                    HorizontalAlignment =
                        HorizontalAlignment.Center
                };

                TrustedDevicesPanel.Children.Add(emptyCard);
            }

            Log(
                $"[UI] Trusted Devices rendered: {count}"
            );
        }

        private static string GetJsonString(
            JsonElement element,
            string propertyName)
        {
            if (!element.TryGetProperty(
                    propertyName,
                    out var property))
            {
                return string.Empty;
            }

            return property.ValueKind == JsonValueKind.String
                ? property.GetString() ?? string.Empty
                : string.Empty;
        }

        // =========================================================
        // LOGGING
        // =========================================================

        private static void Log(string message)
        {
            System.Diagnostics.Debug.WriteLine(message);
            Console.WriteLine(message);
        }

        // =========================================================
        // ERROR
        // =========================================================

        private async Task ShowErrorAsync(
            string message)
        {
            var dialog = new ContentDialog
            {
                Title = "LazyPC",

                Content =
                    new TextBlock
                    {
                        Text = message,
                        TextWrapping =
                            Microsoft.UI.Xaml.TextWrapping.Wrap
                    },

                CloseButtonText = "OK"
            };

            var root = Content?.XamlRoot;

            if (root is null)
            {
                Log(
                    $"[UI] Cannot show error dialog because XamlRoot is null: {message}"
                );

                return;
            }

            dialog.XamlRoot = root;

            try
            {
                Activate();

                IntPtr hwnd =
                    WinRT.Interop.WindowNative.GetWindowHandle(
                        this
                    );

                if (hwnd != IntPtr.Zero)
                {
                    SetForegroundWindow(hwnd);
                }

                await dialog.ShowAsync();
            }
            catch (Exception ex)
            {
                Log(
                    $"[UI] Error dialog failed: {ex}"
                );
            }
        }
    }
}