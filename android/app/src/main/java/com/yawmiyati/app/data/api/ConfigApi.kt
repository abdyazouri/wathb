package com.yawmiyati.app.data.api

import com.google.gson.annotations.SerializedName
import com.yawmiyati.app.BuildConfig
import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import retrofit2.http.GET

/** GET app/config/ — the server sends snake_case keys. */
data class AppConfigResponse(
    @SerializedName("min_supported_version_code") val minSupportedVersionCode: Int = 0,
    @SerializedName("latest_version_code") val latestVersionCode: Int = 0,
    @SerializedName("apk_download_url") val apkDownloadUrl: String = "",
    @SerializedName("support_whatsapp") val supportWhatsapp: String = "",
)

interface ConfigApiService {
    @GET("app/config/")
    suspend fun getConfig(): AppConfigResponse
}

object ConfigApi {
    private val retrofit by lazy {
        Retrofit.Builder()
            .baseUrl(BuildConfig.API_BASE_URL)
            .client(OkHttpClient())
            .addConverterFactory(GsonConverterFactory.create())
            .build()
    }
    val service: ConfigApiService by lazy { retrofit.create(ConfigApiService::class.java) }
}
