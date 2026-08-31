package com.example.lazypc.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Computer
import androidx.compose.material.icons.filled.Link
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.input.OffsetMapping
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.input.TransformedText

@Composable
fun ConnectByIdScreen(
    connecting: Boolean,
    connected: Boolean,
    awaitingSecret: Boolean,
    error: String?,
    onConnect: (String) -> Unit,
    onSubmitSecret: (String) -> Unit,
    onBack: () -> Unit
) {
    var pcId by remember {
        mutableStateOf("")
    }

    var secret by remember {
        mutableStateOf("")
    }

    // This is a UI state, not the connection state.
    // entering the 9-digit code screen must NOT start the spinner.
    var verifyingCode by remember { mutableStateOf(false) }

    // Stop the spinner when the authentication attempt finishes or fails.
    LaunchedEffect(awaitingSecret, connecting, error) {
        if (!awaitingSecret || !connecting || error != null) {
            verifyingCode = false
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background)
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 8.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            IconButton(
                onClick = onBack,
                enabled = true
            ) {
                Icon(
                    imageVector = Icons.Default.ArrowBack,
                    contentDescription = "Назад"
                )
            }

            Text(
                text = if (awaitingSecret) {
                    "Подтверждение подключения"
                } else {
                    "Подключение по ID"
                },
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.SemiBold
            )
        }

        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 24.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Spacer(modifier = Modifier.height(42.dp))

            Box(
                modifier = Modifier
                    .size(88.dp)
                    .clip(RoundedCornerShape(26.dp))
                    .background(
                        MaterialTheme.colorScheme.primary.copy(alpha = 0.12f)
                    ),
                contentAlignment = Alignment.Center
            ) {
                Icon(
                    imageVector = if (awaitingSecret) {
                        Icons.Default.Lock
                    } else {
                        Icons.Default.Computer
                    },
                    contentDescription = null,
                    modifier = Modifier.size(46.dp),
                    tint = MaterialTheme.colorScheme.primary
                )
            }

            Spacer(modifier = Modifier.height(24.dp))

            if (awaitingSecret) {
                // -----------------------------
                // Stage 2: one-time secret
                // -----------------------------
                Text(
                    text = "Введите код компьютера",
                    style = MaterialTheme.typography.headlineSmall,
                    fontWeight = FontWeight.Bold,
                    textAlign = TextAlign.Center
                )

                Spacer(modifier = Modifier.height(8.dp))

                Text(
                    text = "Введите одноразовый 9-значный код,\n" +
                            "показанный на компьютере",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onBackground.copy(alpha = 0.65f),
                    textAlign = TextAlign.Center
                )

                Spacer(modifier = Modifier.height(32.dp))

                OutlinedTextField(
                    value = secret,
                    onValueChange = { value ->
                        secret = value
                            .filter { it.isDigit() }
                            .take(9)
                    },
                    modifier = Modifier.fillMaxWidth(),
                    enabled = !verifyingCode,
                    singleLine = true,
                    label = {
                        Text("Код компьютера")
                    },

                    leadingIcon = {
                        Icon(
                            imageVector = Icons.Default.Lock,
                            contentDescription = null
                        )
                    },
                    keyboardOptions = KeyboardOptions(
                        keyboardType = KeyboardType.Number
                    ),
                    visualTransformation = GroupedDigitsVisualTransformation(),
                    shape = RoundedCornerShape(16.dp)
                )

                Spacer(modifier = Modifier.height(8.dp))

                Text(
                    text = "${secret.length} / 9",
                    modifier = Modifier.fillMaxWidth(),
                    textAlign = TextAlign.End,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onBackground.copy(alpha = 0.5f)
                )

                Spacer(modifier = Modifier.height(24.dp))

                Button(
                    onClick = {
                        verifyingCode = true
                        onSubmitSecret(secret)
                    },
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(54.dp),
                    enabled = secret.length == 9 && !verifyingCode,
                    shape = RoundedCornerShape(16.dp)
                ) {
                    if (verifyingCode) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(22.dp),
                            strokeWidth = 2.dp
                        )

                        Spacer(modifier = Modifier.size(10.dp))

                        Text("Проверка кода...")
                    } else {
                        Text(
                            text = "Подтвердить",
                            fontWeight = FontWeight.SemiBold
                        )
                    }
                }

                Spacer(modifier = Modifier.height(24.dp))
            } else {
                // -----------------------------
                // Stage 1: PC ID
                // -----------------------------
                Text(
                    text = "Подключиться к компьютеру",
                    style = MaterialTheme.typography.headlineSmall,
                    fontWeight = FontWeight.Bold,
                    textAlign = TextAlign.Center
                )

                Spacer(modifier = Modifier.height(8.dp))

                Text(
                    text = "Введите ID компьютера,\nк которому хотите подключиться",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onBackground.copy(alpha = 0.65f),
                    textAlign = TextAlign.Center
                )

                Spacer(modifier = Modifier.height(32.dp))

                OutlinedTextField(
                    value = pcId,
                    onValueChange = { value ->
                        pcId = value
                            .filter { it.isDigit() }
                            .take(9)
                    },
                    modifier = Modifier.fillMaxWidth(),
                    enabled = !connecting,
                    singleLine = true,
                    label = {
                        Text("ID компьютера")
                    },

                    leadingIcon = {
                        Icon(
                            imageVector = Icons.Default.Link,
                            contentDescription = null
                        )
                    },
                    keyboardOptions = KeyboardOptions(
                        keyboardType = KeyboardType.Number
                    ),
                    visualTransformation = GroupedDigitsVisualTransformation(),
                    shape = RoundedCornerShape(16.dp)
                )

                Spacer(modifier = Modifier.height(8.dp))

                Text(
                    text = "${pcId.length} / 9",
                    modifier = Modifier.fillMaxWidth(),
                    textAlign = TextAlign.End,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onBackground.copy(alpha = 0.5f)
                )

                Spacer(modifier = Modifier.height(24.dp))

                Button(
                    onClick = {
                        onConnect(pcId)
                    },
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(54.dp),
                    enabled = pcId.length == 9 && !connecting,
                    shape = RoundedCornerShape(16.dp)
                ) {
                    if (connecting) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(22.dp),
                            strokeWidth = 2.dp
                        )

                        Spacer(modifier = Modifier.size(10.dp))

                        Text("Поиск компьютера...")
                    } else {
                        Text(
                            text = "Подключиться",
                            fontWeight = FontWeight.SemiBold
                        )
                    }
                }

                Spacer(modifier = Modifier.height(24.dp))
            }

            if (error != null) {
                Text(
                    text = error,
                    modifier = Modifier.fillMaxWidth(),
                    textAlign = TextAlign.Center,
                    color = MaterialTheme.colorScheme.error,
                    style = MaterialTheme.typography.bodyMedium
                )

                Spacer(modifier = Modifier.height(8.dp))
            }

            Text(
                text = "Это разовое подключение.\n" +
                        "Компьютер не будет добавлен\n" +
                        "в список доверенных.",
                modifier = Modifier.fillMaxWidth(),
                textAlign = TextAlign.Center,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onBackground.copy(alpha = 0.55f)
            )
        }
    }
}

/**
 * Shows 9 digits as 123 456 789 while keeping the actual
 * TextField value as raw digits. Therefore the cryptographic
 * layer still receives exactly the original 9-digit string.
 */
private class GroupedDigitsVisualTransformation : VisualTransformation {
    override fun filter(text: AnnotatedString): TransformedText {
        val raw = text.text

        if (raw.isEmpty()) {
            return TransformedText(
                AnnotatedString(""),
                OffsetMapping.Identity
            )
        }

        val builder = StringBuilder()

        raw.forEachIndexed { index, char ->
            if (index > 0 && index % 3 == 0) {
                builder.append(' ')
            }
            builder.append(char)
        }

        val transformed = builder.toString()

        val offsetMapping = object : OffsetMapping {
            override fun originalToTransformed(offset: Int): Int {
                if (offset <= 0) return 0

                val spacesBefore = (offset - 1) / 3
                return offset + spacesBefore
            }

            override fun transformedToOriginal(offset: Int): Int {
                if (offset <= 0) return 0

                var original = 0
                var transformedIndex = 0

                while (
                    transformedIndex < offset &&
                    original < raw.length
                ) {
                    if (
                        transformedIndex < transformed.length &&
                        transformed[transformedIndex] == ' '
                    ) {
                        transformedIndex++
                    } else {
                        transformedIndex++
                        original++
                    }
                }

                return original.coerceIn(0, raw.length)
            }
        }

        return TransformedText(
            AnnotatedString(transformed),
            offsetMapping
        )
    }
}
