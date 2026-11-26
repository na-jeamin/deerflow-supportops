import Link from "next/link";

import { Footer } from "@/components/landing/footer";
import { Header } from "@/components/landing/header";
import { Button } from "@/components/ui/button";
import { PROJECT_NAME } from "@/core/branding";
import { DEFAULT_LOCALE } from "@/core/i18n/locale";

export default function LandingPage() {
  return (
    <div className="min-h-screen w-full overflow-x-clip bg-[#0a0a0a]">
      <Header homeURL="/" locale={DEFAULT_LOCALE} />
      <main className="mx-auto flex min-h-[70svh] w-full max-w-4xl flex-col items-center justify-center gap-6 px-6 pt-28 text-center text-white">
        <p className="text-sm text-white/60">基于 DeerFlow 的订单与售后助手</p>
        <h1 className="text-4xl font-semibold sm:text-5xl">{PROJECT_NAME}</h1>
        <p className="max-w-2xl leading-8 text-white/75">
          在聊天中查询订单、登记售后申请；在工作台核对内容、修改与审批，批准后创建工单。
        </p>
        <div className="flex flex-wrap justify-center gap-4">
          <Button asChild size="lg">
            <Link href="/workspace/chats/new">进入聊天 / Chat</Link>
          </Button>
          <Button asChild size="lg" variant="secondary">
            <Link href="/workspace/supportops">售后工单 / After-sales</Link>
          </Button>
        </div>
        <p className="max-w-2xl text-sm leading-7 text-white/60">
          订单使用固定演示数据，申请和工单保存在
          SQLite。修改申请后需要重新审批，同一申请重复执行返回同一工单。
          <br />
          Demo orders · Human approval · Revision checks · Idempotent tickets
        </p>
      </main>
      <Footer />
    </div>
  );
}
