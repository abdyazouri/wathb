package com.yawmiyati.app

import com.yawmiyati.app.data.api.AuthApi
import com.yawmiyati.app.data.api.SessionRefreshUnavailableException
import com.yawmiyati.app.data.api.TokenAuthenticator
import com.yawmiyati.app.data.auth.SessionEventBus
import com.yawmiyati.app.data.auth.TokenStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.sync.Mutex
import okhttp3.HttpUrl
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.SocketPolicy
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.fail
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

class TokenAuthenticatorTest {

    private val server = MockWebServer()
    private lateinit var fakeTokenStore: FakeTokenStore
    private lateinit var client: OkHttpClient

    @Before
    fun setUp() {
        server.start()
        fakeTokenStore = FakeTokenStore(access = "stale_token", refresh = "refresh_token")
        client = buildClient(refreshBaseUrl = server.url("/"))
    }

    /** Main client whose authenticator refreshes against [refreshBaseUrl]. */
    private fun buildClient(refreshBaseUrl: HttpUrl): OkHttpClient {
        // Separate refresh client — no authenticator to avoid recursion.
        val refreshClient = OkHttpClient.Builder()
            .readTimeout(1, TimeUnit.SECONDS)
            .build()
        val refreshApi = Retrofit.Builder()
            .baseUrl(refreshBaseUrl)
            .client(refreshClient)
            .addConverterFactory(GsonConverterFactory.create())
            .build()
            .create(AuthApi::class.java)

        val authenticator = TokenAuthenticator(
            tokenStore = fakeTokenStore,
            refreshApi = refreshApi,
            mutex = Mutex()
        )

        return OkHttpClient.Builder()
            .authenticator(authenticator)
            .addInterceptor { chain ->
                val token = fakeTokenStore.getAccessToken()
                val req = if (token != null) {
                    chain.request().newBuilder()
                        .header("Authorization", "Bearer $token")
                        .build()
                } else chain.request()
                chain.proceed(req)
            }
            .build()
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    /** (أ) 401 → تحديث الرمز → إعادة المحاولة بنجاح */
    @Test
    fun `401 triggers refresh then retries and succeeds`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(401).setBody(""))
        server.enqueue(
            MockResponse().setResponseCode(200)
                .addHeader("Content-Type", "application/json")
                .setBody("""{"access":"new_access","refresh":"new_refresh"}""")
        )
        server.enqueue(MockResponse().setResponseCode(200).setBody("ok"))

        val response = client.newCall(
            Request.Builder().url(server.url("/api/")).build()
        ).execute()

        assertEquals(200, response.code)
        assertEquals("new_access", fakeTokenStore.getAccessToken())
        response.close()

        // Verify request sequence: GET /api/ → POST /auth/token/refresh/ → GET /api/
        val req1 = server.takeRequest(2, TimeUnit.SECONDS)
        val req2 = server.takeRequest(2, TimeUnit.SECONDS)
        val req3 = server.takeRequest(2, TimeUnit.SECONDS)
        assertTrue(req1?.path?.startsWith("/api/") == true)
        assertTrue(req2?.path?.contains("token/refresh") == true)
        assertTrue(req3?.path?.startsWith("/api/") == true)
    }

    /** (ب) طلبان متوازيان يُنتجان طلب تحديث واحد فقط */
    @Test
    fun `two parallel 401s cause exactly one refresh call`() = runBlocking {
        // Both parallel GETs get 401, one refresh succeeds, both retries succeed.
        server.enqueue(MockResponse().setResponseCode(401).setBody(""))
        server.enqueue(MockResponse().setResponseCode(401).setBody(""))
        server.enqueue(
            MockResponse().setResponseCode(200)
                .addHeader("Content-Type", "application/json")
                .setBody("""{"access":"new_access","refresh":"new_refresh"}""")
        )
        server.enqueue(MockResponse().setResponseCode(200).setBody("ok1"))
        server.enqueue(MockResponse().setResponseCode(200).setBody("ok2"))

        val req = Request.Builder().url(server.url("/api/")).build()
        val d1 = async(Dispatchers.IO) { client.newCall(req).execute() }
        val d2 = async(Dispatchers.IO) { client.newCall(req).execute() }
        val r1 = d1.await()
        val r2 = d2.await()

        assertEquals(200, r1.code)
        assertEquals(200, r2.code)
        r1.close()
        r2.close()

        // Count refresh requests among all MockWebServer hits.
        val allRequests = (1..server.requestCount).map {
            server.takeRequest(1, TimeUnit.SECONDS)
        }
        val refreshCount = allRequests.count { it?.path?.contains("token/refresh") == true }
        assertEquals(1, refreshCount)
    }

    /** (ج) تحديث الرمز يُرجع 401 → مسح الرموز وإصدار sessionExpired مرة واحدة */
    @Test
    fun `refresh 401 clears tokens and emits sessionExpired exactly once`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(401).setBody(""))
        server.enqueue(MockResponse().setResponseCode(401).setBody(""))

        val sessionExpiredCount = AtomicInteger(0)
        val latch = CountDownLatch(1)
        val collectJob = launch(Dispatchers.Unconfined) {
            SessionEventBus.sessionExpired.collect {
                if (sessionExpiredCount.incrementAndGet() == 1) latch.countDown()
            }
        }

        client.newCall(
            Request.Builder().url(server.url("/api/")).build()
        ).execute().close()

        // Event is emitted synchronously inside the authenticator before execute() returns;
        // latch guards against any scheduler delay.
        assertTrue("sessionExpired not emitted within 2s", latch.await(2, TimeUnit.SECONDS))
        collectJob.cancel()

        assertTrue(fakeTokenStore.clearCalled)
        assertEquals(1, sessionExpiredCount.get())
    }

    /** (د) تحديث الرمز يُرجع 400 (رمز غير صالح أو محظور) → مسح الجلسة */
    @Test
    fun `refresh 400 clears tokens and emits sessionExpired`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(401).setBody(""))
        server.enqueue(MockResponse().setResponseCode(400).setBody("""{"detail":"bad token"}"""))

        val expired = countSessionExpired {
            client.newCall(Request.Builder().url(server.url("/api/")).build()).execute().close()
        }

        assertTrue(fakeTokenStore.clearCalled)
        assertEquals(1, expired)
    }

    /** (هـ) لا اتصال أثناء التحديث → تبقى الجلسة ورسالة عربية */
    @Test
    fun `refresh network error keeps session and throws Arabic no-connection error`() = runBlocking {
        val dead = MockWebServer().apply { start() }
        val deadUrl = dead.url("/")
        dead.shutdown()  // connection refused from now on
        client = buildClient(refreshBaseUrl = deadUrl)
        server.enqueue(MockResponse().setResponseCode(401).setBody(""))

        assertSessionKeptAndNoConnectionError()
    }

    /** (و) انتهاء مهلة التحديث → تبقى الجلسة */
    @Test
    fun `refresh timeout keeps session and throws Arabic no-connection error`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(401).setBody(""))
        server.enqueue(MockResponse().setSocketPolicy(SocketPolicy.NO_RESPONSE))

        assertSessionKeptAndNoConnectionError()
    }

    /** (ز) خطأ 5xx من الخادم أثناء التحديث → تبقى الجلسة */
    @Test
    fun `refresh 500 keeps session and throws Arabic no-connection error`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(401).setBody(""))
        server.enqueue(MockResponse().setResponseCode(500).setBody("Internal Server Error"))

        assertSessionKeptAndNoConnectionError()
    }

    @Test
    fun `refresh 503 keeps session and throws Arabic no-connection error`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(401).setBody(""))
        server.enqueue(MockResponse().setResponseCode(503).setBody("<html>Service Unavailable</html>"))

        assertSessionKeptAndNoConnectionError()
    }

    /** (ح) بعد فشل مؤقت، إعادة المحاولة تنجح بالجلسة نفسها — كما يفعل المستودع (Retrofit suspend). */
    @Test
    fun `retry after a failed refresh succeeds and repository sees the Arabic message`() = runBlocking {
        val api = Retrofit.Builder()
            .baseUrl(server.url("/"))
            .client(client)
            .addConverterFactory(GsonConverterFactory.create())
            .build()
            .create(AuthApi::class.java)

        server.enqueue(MockResponse().setResponseCode(401).setBody(""))
        server.enqueue(MockResponse().setResponseCode(502).setBody(""))
        val message = try {
            api.me()
            null
        } catch (e: Exception) {
            e.localizedMessage  // what the repositories' networkMessage() falls back to
        }
        assertEquals(SessionRefreshUnavailableException.NO_CONNECTION_MESSAGE, message)
        assertEquals("refresh_token", fakeTokenStore.getRefreshToken())

        // Connection is back: the user taps retry.
        server.enqueue(MockResponse().setResponseCode(401).setBody(""))
        server.enqueue(
            MockResponse().setResponseCode(200)
                .addHeader("Content-Type", "application/json")
                .setBody("""{"access":"new_access","refresh":"new_refresh"}""")
        )
        server.enqueue(
            MockResponse().setResponseCode(200)
                .addHeader("Content-Type", "application/json")
                .setBody("""{"id":"u1","phone":"+970599000001","role":"WORKER","is_verified":true,"date_joined":"2026-11-01T00:00:00Z"}""")
        )
        val retry = api.me()
        assertTrue(retry.isSuccessful)
        assertEquals("new_access", fakeTokenStore.getAccessToken())
        assertFalse(fakeTokenStore.clearCalled)
    }

    private suspend fun assertSessionKeptAndNoConnectionError() {
        val expired = countSessionExpired {
            try {
                client.newCall(Request.Builder().url(server.url("/api/")).build()).execute().close()
                fail("expected SessionRefreshUnavailableException")
            } catch (e: SessionRefreshUnavailableException) {
                assertEquals(SessionRefreshUnavailableException.NO_CONNECTION_MESSAGE, e.message)
            }
        }
        assertFalse(fakeTokenStore.clearCalled)
        assertEquals("stale_token", fakeTokenStore.getAccessToken())
        assertEquals("refresh_token", fakeTokenStore.getRefreshToken())
        assertEquals(0, expired)
    }

    /** Runs [block] and returns how many sessionExpired events it emitted. */
    private suspend fun countSessionExpired(block: () -> Unit): Int = coroutineScope {
        val count = AtomicInteger(0)
        val job = launch(Dispatchers.Unconfined) { SessionEventBus.sessionExpired.collect { count.incrementAndGet() } }
        block()
        job.cancel()
        count.get()
    }

    // ── Helpers ──────────────────────────────────────────────────────────────────

    private class FakeTokenStore(access: String?, refresh: String?) : TokenStore {
        private var _access = access
        private var _refresh = refresh
        var clearCalled = false

        override fun getAccessToken(): String? = _access
        override fun getRefreshToken(): String? = _refresh
        override fun saveTokens(access: String, refresh: String) {
            _access = access
            _refresh = refresh
        }
        override fun clear() {
            clearCalled = true
            _access = null
            _refresh = null
        }
    }
}
