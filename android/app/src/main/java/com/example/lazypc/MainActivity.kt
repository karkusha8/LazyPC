package com.example.lazypc

import com.example.lazypc.ui.screens.HomeScreen
import com.example.lazypc.ui.screens.ConnectByIdScreen
import com.example.lazypc.ui.screens.RemoteSessionScreen
import android.os.Bundle
import android.hardware.biometrics.BiometricPrompt
import android.os.CancellationSignal
import android.content.DialogInterface
import android.widget.Toast
import android.content.ComponentName
import android.content.ServiceConnection
import android.os.IBinder
import android.util.Log
import android.os.Handler
import android.os.Looper
import android.content.Intent
import androidx.activity.compose.setContent
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.app.AlertDialog
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.core.content.ContextCompat
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.codescanner.GmsBarcodeScannerOptions
import com.google.mlkit.vision.codescanner.GmsBarcodeScanning
import com.example.lazypc.input.mouse.CursorState
import com.example.lazypc.input.mouse.MouseEmitter
import com.example.lazypc.input.PointerInputRouter
import com.example.lazypc.input.events.GestureEvent
import com.example.lazypc.input.gesture.ClientGestureEngine
import com.example.lazypc.input.keyboard.core.ActionResolver
import com.example.lazypc.input.keyboard.core.KeyboardEngine
import com.example.lazypc.input.keyboard.emit.KeyboardEmitter
import com.example.lazypc.input.keyboard.mapping.LanguageEN
import com.example.lazypc.security.SecurityKeyStore
import com.example.lazypc.security.TrustedPairing
import com.example.lazypc.video.CustomVideoRenderer
import com.example.lazypc.service.WebRTCForegroundService
import com.example.lazypc.security.TrustedPc
import com.example.lazypc.security.TrustedPcStore
import org.webrtc.VideoFrame
import org.webrtc.VideoSink
import org.webrtc.VideoTrack

class MainActivity : AppCompatActivity() {

    companion object {
        private const val TAG_APP = "APP"
        private const val TAG_WS = "WS"
        private const val TAG_INPUT = "INPUT"

        private const val SIGNALING_URL =
            "ws://192.168.0.148:8000/ws"
    }

    private var pendingSecureLinkCodeAccepted: (() -> Unit)? = null
    private var webRtcService: WebRTCForegroundService? = null
    private var serviceBound = false

    private lateinit var trustedPcStore: TrustedPcStore
    private var trustedPcs by mutableStateOf<List<TrustedPc>>(emptyList())
    private var pcOnline by mutableStateOf<Map<String, Boolean>>(emptyMap())

    private lateinit var renderer: CustomVideoRenderer

    private var currentVideoTrack: VideoTrack? = null

    private var detectedVideoWidth by mutableIntStateOf(0)
    private var detectedVideoHeight by mutableIntStateOf(0)

    private var lastVideoWidth = 0
    private var lastVideoHeight = 0

    private val videoSizeSink = object : VideoSink {
        override fun onFrame(frame: VideoFrame) {
            val width = frame.rotatedWidth
            val height = frame.rotatedHeight

            if (width <= 0 || height <= 0) return

            if (
                width == lastVideoWidth &&
                height == lastVideoHeight
            ) {
                return
            }

            lastVideoWidth = width
            lastVideoHeight = height

            Log.d(
                TAG_APP,
                "🎬 VIDEO SIZE: ${width}x${height}"
            )

            runOnUiThread {
                detectedVideoWidth = width
                detectedVideoHeight = height
            }
        }
    }

    private lateinit var mouseEmitter: MouseEmitter
    private lateinit var gestureEngine: ClientGestureEngine
    private lateinit var pointerInputRouter: PointerInputRouter

    private val cursorState =
        CursorState()

    private var mouseAreaWidth = 0f
    private var mouseAreaHeight = 0f

    private var videoAreaWidth = 0f
    private var videoAreaHeight = 0f

    // Valid mouse coordinates in fitted-video space.
    // At 1x these are the whole video; while zoomed they are the
    // currently visible source rectangle.
    private var mouseActionMinX = 0f
    private var mouseActionMaxX = Float.POSITIVE_INFINITY
    private var mouseActionMinY = 0f
    private var mouseActionMaxY = Float.POSITIVE_INFINITY

    private lateinit var keyboardEngine: KeyboardEngine
    private lateinit var keyboardEmitter: KeyboardEmitter

    private var dragModeEnabled = false

    private var sessionConnecting by mutableStateOf(false)
    private var sessionConnected by mutableStateOf(false)
    private var trustedConnectionError by mutableStateOf<String?>(null)

    private var simpleConnectionConnecting by mutableStateOf(false)
    private var simpleConnectionConnected by mutableStateOf(false)
    private var simpleConnectionError by mutableStateOf<String?>(null)
    private var simpleConnectionAwaitingSecret by mutableStateOf(false)

    private var connectionState by mutableStateOf<ConnectionState>(
        ConnectionState.Disconnected
    )

    // True while the user is on the one-time "Connect by ID" screen.
    // It is intentionally not persisted.
    private var showConnectById by mutableStateOf(false)

    private val lifecycleHandler = Handler(Looper.getMainLooper())

    private val pcStatusPoll = object : Runnable {
        override fun run() {
            if (!finishing && !sessionConnected && !simpleConnectionConnected) {
                // Secure Link v4 devices are identified by their pinned public key.
                // The legacy numeric-code status polling does not apply to v4.


                lifecycleHandler.postDelayed(this, 10_000L)
            }
        }
    }

    private var recoveryScheduled = false
    private var recoveryInProgress = false
    private var finishing = false
    private var sessionStarted = false

    private val serviceConnection = object : ServiceConnection {
        override fun onServiceConnected(
            name: ComponentName?,
            service: IBinder?
        ) {
            val binder = service as? WebRTCForegroundService.LocalBinder
                ?: return

            webRtcService = binder.service()
            serviceBound = true

            Log.d(TAG_APP, "🟢 WEBRTC SERVICE BOUND")
            initializeFromService()

            lifecycleHandler.removeCallbacks(pcStatusPoll)
            lifecycleHandler.post(pcStatusPoll)
        }

        override fun onServiceDisconnected(name: ComponentName?) {
            serviceBound = false
            webRtcService = null
            connectionState = ConnectionState.Disconnected
            Log.w(TAG_APP, "🔴 WEBRTC SERVICE DISCONNECTED")
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        WindowCompat.setDecorFitsSystemWindows(
            window,
            false
        )

        WindowInsetsControllerCompat(
            window,
            window.decorView
        ).apply {
            hide(WindowInsetsCompat.Type.systemBars())
            systemBarsBehavior =
                WindowInsetsControllerCompat
                    .BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        }

        Log.d(TAG_APP, "🚀 LAZYPC START")

        trustedPcStore = TrustedPcStore(this)
        trustedPcs = trustedPcStore.list()

        val serviceIntent =
            Intent(this, WebRTCForegroundService::class.java)

        ContextCompat.startForegroundService(
            this,
            serviceIntent
        )

        bindService(
            serviceIntent,
            serviceConnection,
            BIND_AUTO_CREATE
        )
    }

    private fun startTrustedDevicePairing() {
        val service = webRtcService ?: run {
            Toast.makeText(
                this,
                "WebRTC service ещё не готов",
                Toast.LENGTH_SHORT
            ).show()
            return
        }

        val options = GmsBarcodeScannerOptions.Builder()
            .setBarcodeFormats(Barcode.FORMAT_QR_CODE)
            .enableAutoZoom()
            .build()

        val scanner = GmsBarcodeScanning.getClient(this, options)

        scanner.startScan()
            .addOnSuccessListener { barcode ->
                val payload = barcode.rawValue?.trim()

                if (payload.isNullOrEmpty()) {
                    Toast.makeText(
                        this,
                        "QR-код пустой",
                        Toast.LENGTH_SHORT
                    ).show()
                    return@addOnSuccessListener
                }

                try {
                    // Secure Link v4 uses the URI QR format and must not
                    // be passed through the legacy pipe-delimited parser.
                    com.example.lazypc.security.SecureLinkV4.parseQrPayload(payload)

                    service.connectTrustedPairingSession(payload)

                    Toast.makeText(
                        this,
                        "Trusted Device pairing запущен",
                        Toast.LENGTH_SHORT
                    ).show()
                } catch (error: Throwable) {
                    Log.e(
                        TAG_APP,
                        "Trusted Device QR rejected",
                        error
                    )

                    Toast.makeText(
                        this,
                        "Неверный LazyPC QR-код",
                        Toast.LENGTH_SHORT
                    ).show()
                }
            }
            .addOnCanceledListener {
                Log.d(
                    TAG_APP,
                    "Trusted Device QR scan cancelled"
                )
            }
            .addOnFailureListener { error ->
                Log.e(
                    TAG_APP,
                    "Trusted Device QR scanner failed",
                    error
                )

                Toast.makeText(
                    this,
                    "Не удалось открыть QR-сканер",
                    Toast.LENGTH_SHORT
                ).show()
            }
    }

    private fun initializeFromService() {
        val service = webRtcService ?: return

        val eglContext = service.eglContext()
        val webrtc = service.webRtcClient()

        mouseEmitter = MouseEmitter(webrtc)

        gestureEngine =
            ClientGestureEngine(
                isDragModeEnabled = {
                    dragModeEnabled
                },

                emit = { event ->
                    when (event) {
                        is GestureEvent.Move -> {
                            val targetX =
                                (cursorState.x + event.dx).coerceIn(
                                    mouseActionMinX,
                                    mouseActionMaxX
                                )

                            val targetY =
                                (cursorState.y + event.dy).coerceIn(
                                    mouseActionMinY,
                                    mouseActionMaxY
                                )

                            val actualDx = targetX - cursorState.x
                            val actualDy = targetY - cursorState.y

                            if (actualDx != 0f || actualDy != 0f) {
                                mouseEmitter.sendMove(
                                    actualDx,
                                    actualDy
                                )

                                cursorState.move(
                                    dx = actualDx,
                                    dy = actualDy,
                                    width = videoAreaWidth,
                                    height = videoAreaHeight
                                )
                            }
                        }

                        GestureEvent.Tap -> {
                            mouseEmitter.sendTap()
                        }

                        GestureEvent.DoubleTap -> {
                            mouseEmitter.sendDoubleTap()
                        }

                        GestureEvent.ContextMenu -> {
                            mouseEmitter.sendRightClick()
                        }

                        GestureEvent.DragStart -> {
                            mouseEmitter.sendDragStart()
                        }

                        is GestureEvent.DragMove -> {
                            val targetX =
                                (cursorState.x + event.dx).coerceIn(
                                    mouseActionMinX,
                                    mouseActionMaxX
                                )

                            val targetY =
                                (cursorState.y + event.dy).coerceIn(
                                    mouseActionMinY,
                                    mouseActionMaxY
                                )

                            val actualDx = targetX - cursorState.x
                            val actualDy = targetY - cursorState.y

                            if (actualDx != 0f || actualDy != 0f) {
                                mouseEmitter.sendDragMove(
                                    actualDx,
                                    actualDy
                                )

                                cursorState.move(
                                    dx = actualDx,
                                    dy = actualDy,
                                    width = videoAreaWidth,
                                    height = videoAreaHeight
                                )
                            }
                        }

                        GestureEvent.DragEnd -> {
                            mouseEmitter.sendDragEnd()
                        }

                        is GestureEvent.Scroll -> {
                            mouseEmitter.sendScroll(event.dy)
                        }
                    }
                }
            )

        pointerInputRouter =
            PointerInputRouter(gestureEngine)

        Log.d(TAG_INPUT, "✅ Mouse initialized")

        keyboardEngine =
            KeyboardEngine(
                resolver = ActionResolver(),
                language = LanguageEN()
            )

        keyboardEmitter = KeyboardEmitter(webrtc)

        setContent {
            if (sessionConnected || simpleConnectionConnected) {
                RemoteSessionScreen(
                    eglContext = eglContext,
                    videoWidth = detectedVideoWidth,
                    videoHeight = detectedVideoHeight,

                    onSurfaceCreated = { surface ->
                        if (::renderer.isInitialized) {
                            currentVideoTrack?.removeSink(renderer)
                        }

                        renderer = surface
                        currentVideoTrack?.addSink(renderer)
                        currentVideoTrack?.addSink(videoSizeSink)
                    },

                    onTouch = { event ->
                        pointerInputRouter.onTouch(event)
                    },

                    cursorState = cursorState,

                    onMouseAreaSizeChanged = { width, height ->
                        mouseAreaWidth = width
                        mouseAreaHeight = height
                    },

                    onVideoAreaSizeChanged = { width, height ->
                        videoAreaWidth = width
                        videoAreaHeight = height

                        mouseActionMinX = 0f
                        mouseActionMaxX = width
                        mouseActionMinY = 0f
                        mouseActionMaxY = height

                        cursorState.initialize(width, height)
                    },

                    onRecenterMouse = { targetX, targetY ->
                        val dx = targetX - cursorState.x
                        val dy = targetY - cursorState.y

                        if (dx != 0f || dy != 0f) {
                            mouseEmitter.sendMove(dx, dy)

                            cursorState.move(
                                dx = dx,
                                dy = dy,
                                width = videoAreaWidth,
                                height = videoAreaHeight
                            )
                        }
                    },

                    onMouseActionBoundsChanged = { minX, maxX, minY, maxY ->
                        mouseActionMinX = minX
                        mouseActionMaxX = maxX
                        mouseActionMinY = minY
                        mouseActionMaxY = maxY
                    },

                    keyboardEngine = keyboardEngine,
                    keyboardEmitter = keyboardEmitter,

                    onDragModeChanged = { enabled ->
                        dragModeEnabled = enabled
                        Log.d(TAG_INPUT, "🧲 Drag mode = $enabled")
                    },

                    onDisconnect = {
                        connectionState = ConnectionState.Disconnecting

                        if (simpleConnectionConnected) {
                            webRtcService?.disconnectToPc()
                        } else {
                            webRtcService?.disconnectSession()
                        }

                        // A finished remote session always returns to Home.
                        // Do not pop the navigation stack: ConnectById is
                        // represented by local UI state, so explicitly close
                        // that flow as well.
                        sessionConnecting = false
                        sessionConnected = false
                        simpleConnectionConnecting = false
                        simpleConnectionConnected = false
                        simpleConnectionAwaitingSecret = false
                        simpleConnectionError = null
                        showConnectById = false
                        connectionState = ConnectionState.Disconnected
                    })
            } else if (showConnectById) {
                ConnectByIdScreen(
                    connecting = simpleConnectionConnecting,
                    connected = simpleConnectionConnected,
                    awaitingSecret = simpleConnectionAwaitingSecret,
                    error = simpleConnectionError,

                    onConnect = { pcId ->
                        simpleConnectionError = null
                        simpleConnectionAwaitingSecret = false
                        connectionState = ConnectionState.Connecting
                        webRtcService?.connectToPc(pcId)
                    },

                    onSubmitSecret = { secret ->
                        val accepted = webRtcService?.submitOrdinarySecret(secret) == true
                        if (!accepted) {
                            simpleConnectionError = "Не удалось отправить код"
                        } else {
                            simpleConnectionError = null
                            simpleConnectionAwaitingSecret = true
                            simpleConnectionConnecting = true
                            connectionState = ConnectionState.VerifyingCode
                        }
                    },

                    onBack = {
                        // Back from any stage of the direct ID flow is a real
                        // cancellation, not just a UI navigation event.
                        // The service sends SESSION_CLOSE to the PC and resets
                        // the direct connection state.
                        if (simpleConnectionConnecting || simpleConnectionAwaitingSecret) {
                            webRtcService?.disconnectToPc()
                        }

                        showConnectById = false
                        simpleConnectionConnecting = false
                        simpleConnectionConnected = false
                        simpleConnectionAwaitingSecret = false
                        simpleConnectionError = null
                        connectionState = ConnectionState.Disconnected
                    }
                )
            } else {
                HomeScreen(
                    trustedPcs = trustedPcs,
                    pcOnline = pcOnline,
                    connecting = sessionConnecting,
                    connectionError = trustedConnectionError,
                    onCancelConnection = {
                        webRtcService?.disconnectSession()
                        sessionConnecting = false
                        sessionConnected = false
                        connectionState = ConnectionState.Disconnected
                        trustedConnectionError = "Подключение отменено"
                    },

                    onComputerClick = { pc ->
                        trustedConnectionError = null
                        connectionState = ConnectionState.Connecting
                        webRtcService?.connectTrusted(pc.pcIdentityPublic, pc.hardwareAlias)
                    },

                    onAddComputer = {
                        startTrustedDevicePairing()
                    },

                    onConnectById = {
                        simpleConnectionError = null
                        simpleConnectionAwaitingSecret = false
                        showConnectById = true
                    },
                    onDeleteComputer = { pc ->
                        trustedPcStore.remove(pc.pcIdentityPublic)
                        trustedPcs = trustedPcStore.list()
                        pcOnline = pcOnline - pc.pcIdentityPublic
                        Log.d(TAG_APP, "🗑 Secure Link v4 trusted PC removed locally")
                    },

                    onSettingsClick = {
                        Toast.makeText(
                            this,
                            "Настройки пока в разработке",
                            Toast.LENGTH_SHORT
                        ).show()
                    }
                )
            }
        }

        service.registerUiCallbacks(
            onVideoTrackChanged = { track ->
                runOnUiThread {
                    if (currentVideoTrack === track) {
                        return@runOnUiThread
                    }

                    if (::renderer.isInitialized) {
                        currentVideoTrack
                            ?.removeSink(renderer)
                    }

                    currentVideoTrack
                        ?.removeSink(videoSizeSink)

                    currentVideoTrack = track

                    track?.addSink(videoSizeSink)

                    if (::renderer.isInitialized) {
                        track?.addSink(renderer)
                    }
                }
            },

            onCursorPosition = { normalizedX, normalizedY ->
                runOnUiThread {
                    cursorState.setNormalizedPosition(
                        normalizedX = normalizedX,
                        normalizedY = normalizedY,
                        width = videoAreaWidth,
                        height = videoAreaHeight
                    )
                }
            },

            onSignalingState = { connected ->
                Log.d(
                    TAG_WS,
                    if (connected) {
                        "🟢 SIGNALING CONNECTED [SERVICE]"
                    } else {
                        "🔴 SIGNALING DISCONNECTED [SERVICE]"
                    }
                )
            },

            onSessionState = { connecting, connected ->
                val wasConnected = sessionConnected

                sessionConnecting = connecting
                sessionConnected = connected
                if (connecting || connected) trustedConnectionError = null

                // If an active Trusted Device session ends from the service
                // side, return to Home instead of exposing the old
                // Connect-by-ID screen.
                if (wasConnected && !connected) {
                    showConnectById = false
                    simpleConnectionConnecting = false
                    simpleConnectionConnected = false
                    simpleConnectionAwaitingSecret = false
                    simpleConnectionError = null
                }

                connectionState =
                    when {
                        connected -> ConnectionState.Connected
                        connecting -> ConnectionState.Connecting
                        else -> ConnectionState.Disconnected
                    }
            },
            onSessionError = { message ->
                runOnUiThread {
                    trustedConnectionError = message
                    sessionConnecting = false
                    sessionConnected = false
                    connectionState = ConnectionState.Error(message)
                }
            }
        )

        service.registerSecureLinkPairedCallback { pcIdentityPublic, hardwareAlias ->
            runOnUiThread {
                trustedPcStore.addOrUpdate(pcIdentityPublic, hardwareAlias)
                trustedPcs = trustedPcStore.list()
                Toast.makeText(
                    this,
                    "Компьютер добавлен в доверенные",
                    Toast.LENGTH_SHORT
                ).show()
                // Pairing ends on Home. A session starts only after the user taps the PC.
                sessionConnecting = false
                sessionConnected = false
                connectionState = ConnectionState.Disconnected
            }
        }

        service.registerSecureLinkPairingCallback { code, signature, complete ->
            runOnUiThread {
                // Biometric authentication comes first. The SAS is shown only after
                // StrongBox authorizes this signing operation; pair3 is withheld until
                // Windows validates the manually entered code and sends code_ok.
                pendingSecureLinkCodeAccepted = null
                try {
                    val prompt = BiometricPrompt.Builder(this)
                        .setTitle("Подтвердить сопряжение LazyPC")
                        .setSubtitle("Ключ устройства защищён StrongBox")
                        .setDescription("Подтверди использование ключа, затем введи код на Windows")
                        .setNegativeButton("Отмена", mainExecutor,
                            DialogInterface.OnClickListener { _, _ ->
                                pendingSecureLinkCodeAccepted = null
                                complete(null)
                            })
                        .build()
                    prompt.authenticate(
                        BiometricPrompt.CryptoObject(signature),
                        CancellationSignal(),
                        mainExecutor,
                        object : BiometricPrompt.AuthenticationCallback() {
                            override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                                val authorizedSignature = result.cryptoObject?.signature
                                if (authorizedSignature == null) {
                                    Log.e(TAG_APP, "Secure Link biometric result did not contain a signing operation")
                                    complete(null)
                                    return
                                }

                                val codeDialog = AlertDialog.Builder(this@MainActivity)
                                    .setTitle("Secure Link v4 — код сопряжения")
                                    .setMessage("Введи этот код в окне LazyPC на компьютере:\n\n$code")
                                    .setCancelable(false)
                                    .setNegativeButton("Отмена") { _, _ ->
                                        pendingSecureLinkCodeAccepted = null
                                        complete(null)
                                    }
                                    .create()
                                codeDialog.setOnDismissListener {
                                    // Do not leave a stale authorization callback behind.
                                    pendingSecureLinkCodeAccepted = null
                                }
                                codeDialog.show()
                                pendingSecureLinkCodeAccepted = {
                                    pendingSecureLinkCodeAccepted = null
                                    if (codeDialog.isShowing) codeDialog.dismiss()
                                    complete(authorizedSignature)
                                }
                                Log.i(TAG_APP, "Secure Link biometric authorized; SAS displayed, awaiting Windows code acceptance")
                            }

                            override fun onAuthenticationError(errorCode: Int, errString: CharSequence) {
                                pendingSecureLinkCodeAccepted = null
                                Log.e(TAG_APP, "Secure Link biometric authentication failed: $errString")
                                complete(null)
                            }
                        }
                    )
                } catch (error: Throwable) {
                    pendingSecureLinkCodeAccepted = null
                    Log.e(TAG_APP, "Could not start Secure Link biometric prompt", error)
                    complete(null)
                }
            }
        }

        service.registerSecureLinkCodeAcceptedCallback {
            runOnUiThread {
                val accept = pendingSecureLinkCodeAccepted
                if (accept == null) {
                    Log.e(TAG_APP, "Windows accepted code but biometric authorization/code dialog is not ready")
                } else {
                    accept.invoke()
                }
            }
        }

        service.registerSecureLinkAuthPrompt { signature, complete ->
            runOnUiThread {
                try {
                    val prompt = BiometricPrompt.Builder(this)
                        .setTitle("Подтвердить защищённое подключение LazyPC")
                        .setSubtitle("StrongBox подтверждает доверенное устройство")
                        .setDescription("Разреши этому ПК открыть защищённую сессию")
                        .setNegativeButton("Отмена", mainExecutor,
                            DialogInterface.OnClickListener { _, _ -> complete(null) })
                        .build()
                    prompt.authenticate(
                        BiometricPrompt.CryptoObject(signature),
                        CancellationSignal(),
                        mainExecutor,
                        object : BiometricPrompt.AuthenticationCallback() {
                            override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                                complete(result.cryptoObject?.signature)
                            }
                            override fun onAuthenticationError(errorCode: Int, errString: CharSequence?) {
                                Log.e(TAG_APP, "Secure Link session biometric failed: $errString")
                                complete(null)
                            }
                            override fun onAuthenticationFailed() {
                                Log.w(TAG_APP, "Secure Link session biometric not recognized")
                            }
                        }
                    )
                } catch (error: Throwable) {
                    Log.e(TAG_APP, "Could not start Secure Link session biometric prompt", error)
                    complete(null)
                }
            }
        }

        service.registerPcStatusCallback { _, _ ->
            // Legacy PC-code status events are unrelated to Secure Link v4 identities.
        }

        service.registerOrdinaryAuthCallback {
            runOnUiThread {
                simpleConnectionAwaitingSecret = true
                simpleConnectionError = null
                simpleConnectionConnecting = true
                connectionState = ConnectionState.Connecting
            }
        }

        service.registerDirectConnectionCallback {
                connecting,
                connected,
                error ->
            runOnUiThread {
                val wasConnected = simpleConnectionConnected

                simpleConnectionConnecting = connecting
                simpleConnectionConnected = connected
                simpleConnectionError = error

                // Do not leave the 9-digit-code screen on an authentication
                // error. The code stage ends only after a successful connection.
                if (connected) {
                    simpleConnectionAwaitingSecret = false
                }

                // The direct session can also end without the user pressing
                // the Disconnect button (remote close / service-side close).
                // In that case the user should still land on Home.
                if (wasConnected && !connected && error == null) {
                    showConnectById = false
                    simpleConnectionAwaitingSecret = false
                    simpleConnectionError = null
                }

                connectionState =
                    when {
                        connected -> ConnectionState.Connected
                        connecting -> {
                            if (simpleConnectionAwaitingSecret) {
                                ConnectionState.VerifyingCode
                            } else {
                                ConnectionState.Connecting
                            }
                        }
                        error != null -> ConnectionState.Error(error)
                        else -> ConnectionState.Disconnected
                    }
            }
        }
    }

    override fun onPause() {
        super.onPause()
        Log.d(TAG_APP, "⏸ APP PAUSED")
        // Do not close WebRTC or force a signaling reconnect here.
        // If the OS/network keeps the transport alive, onResume will reuse it.
    }

    override fun onResume() {
        super.onResume()
        Log.d(TAG_APP, "▶ APP RESUMED")

        if (!sessionConnected && !simpleConnectionConnected) {
            lifecycleHandler.removeCallbacks(pcStatusPoll)
            lifecycleHandler.post(pcStatusPoll)
        }

        if (::renderer.isInitialized) {
            currentVideoTrack?.addSink(renderer)
        }

        currentVideoTrack?.addSink(videoSizeSink)
    }

    override fun onDestroy() {
        finishing = true
        lifecycleHandler.removeCallbacksAndMessages(null)

        if (serviceBound) {
            webRtcService?.unregisterUiCallbacks()
            unbindService(serviceConnection)
            serviceBound = false
        }

        if (::renderer.isInitialized) {
            currentVideoTrack?.removeSink(renderer)
            renderer.releaseRenderer()
        }

        currentVideoTrack?.removeSink(videoSizeSink)
        currentVideoTrack = null

        // Do NOT close WebRTC, signaling, or the foreground service here.
        // Those objects belong to the service and must survive Activity
        // recreation/backgrounding.

        super.onDestroy()
    }
}