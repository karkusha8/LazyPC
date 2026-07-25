pluginManagement {
    repositories {
        google {
            content {
                includeGroupByRegex("com\\.android.*")
                includeGroupByRegex("com\\.google.*")
                includeGroupByRegex("androidx.*")
            }
        }
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {

        // 🔥 ОБЯЗАТЕЛЬНО — тут лежит WebRTC
        maven {
            url = uri("https://maven.google.com")
        }

        google()
        mavenCentral()

        // можешь оставить
        maven("https://jitpack.io")
    }
}

rootProject.name = "LazyPC"
include(":app")