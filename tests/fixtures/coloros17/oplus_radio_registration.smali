.method private registerForOplusRadioServiceCallback()V
    .registers 4

    .line 167
    const-string v0, "vendor.oplus.hardware.radio.IRadioStable/OplusRadio"

    const-string v1, "OplusRIL registerForOplusRadioServiceCallback"

    invoke-direct {p0, v1}, Lcom/oplus/internal/telephony/OplusRadioAidl;->logd(Ljava/lang/String;)V

    .line 169
    :try_start_7
    new-instance v1, Ljava/lang/StringBuilder;

    invoke-direct {v1, v0}, Ljava/lang/StringBuilder;-><init>(Ljava/lang/String;)V

    iget v0, p0, Lcom/oplus/internal/telephony/OplusRadioAidl;->mPhoneId:I

    invoke-virtual {v1, v0}, Ljava/lang/StringBuilder;->append(I)Ljava/lang/StringBuilder;

    invoke-virtual {v1}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;

    move-result-object v0

    iget-object v1, p0, Lcom/oplus/internal/telephony/OplusRadioAidl;->mServiceCallback:Landroid/os/IServiceCallback;

    invoke-static {v0, v1}, Landroid/os/ServiceManager;->registerForNotifications(Ljava/lang/String;Landroid/os/IServiceCallback;)V
    :try_end_1a
    .catch Landroid/os/RemoteException; {:try_start_7 .. :try_end_1a} :catch_1b

    return-void

    :catch_1b
    move-exception v0

    .line 171
    new-instance v1, Ljava/lang/StringBuilder;

    const-string v2, "OplusRIL Failed to register for service start notifications. Exception "

    invoke-direct {v1, v2}, Ljava/lang/StringBuilder;-><init>(Ljava/lang/String;)V

    invoke-virtual {v1, v0}, Ljava/lang/StringBuilder;->append(Ljava/lang/Object;)Ljava/lang/StringBuilder;

    invoke-virtual {v1}, Ljava/lang/StringBuilder;->toString()Ljava/lang/String;

    move-result-object v0

    invoke-direct {p0, v0}, Lcom/oplus/internal/telephony/OplusRadioAidl;->logd(Ljava/lang/String;)V

    return-void
.end method