.method public getEnrollmentTotalTimes(I)I
    .registers 4
    .param p1, "sensorId"    # I

    .line 547
    const-string v0, "Biometrics/FingerprintProvider/FingerprintServiceProviderExtImpl"

    const-string/jumbo v1, "getEnrollmentTotalTimes"

    invoke-static {v0, v1}, Lcom/android/server/biometrics/OplusLogUtil;->d(Ljava/lang/String;Ljava/lang/String;)V

    .line 548
    const/4 v0, 0x1

    new-array v0, v0, [B

    const/4 v1, 0x0

    aput-byte v1, v0, v1

    const/16 v1, 0x3f2

    invoke-direct {p0, v1, v0}, Lcom/android/server/biometrics/sensors/fingerprint/aidl/FingerprintServiceProviderExtImpl;->sendFingerprintCmdAndMonitor(I[B)I

    move-result v0

    invoke-static {v0}, Lcom/android/server/biometrics/sensors/dash/DashUdfpsTouchBridge;->normalizeEnrollmentTotal(I)I

    move-result v0

    return v0
.end method
