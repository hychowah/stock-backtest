// Fixed trusted-internal C ABI. Caller keeps all allocations and mappings alive
// through the synchronous call. Invalid external addresses are outside the ABI.
// No pointer is retained. Every shape/range/alias check precedes mutable slices.
#![allow(unused_mut,unused_variables,unused_parens)]
use std::{mem,slice};
const ABI:i32=__ABI__;
const NI:usize=__NINPUTS__;
const NO:usize=__NOUTPUTS__;
const NF:usize=__NFIELDS__;
const WIDTH:usize=11+NF;
const FLAGS:usize=3+NF;
const COLS:[usize;WIDTH]=[__COLUMNS__];
#[repr(C)]
#[derive(Clone,Copy)]
pub struct Buffer { pointer:*mut u8, length:usize }
fn checked(a:usize,b:usize)->Result<usize,i32> { a.checked_mul(b).ok_or(-1) }
impl Buffer {
    fn valid<T>(&self,n:usize)->bool {
        self.length==n && checked(n,mem::size_of::<T>()).is_ok_and(|bytes|
            bytes<=isize::MAX as usize && (n==0 || (!self.pointer.is_null()
                && (self.pointer as usize)%mem::align_of::<T>()==0
                && (self.pointer as usize).checked_add(bytes).is_some())))
    }
    unsafe fn read<'a,T>(&self)->&'a[T] {
        if self.length==0 { &[] } else { slice::from_raw_parts(self.pointer as *const T,self.length) }
    }
    unsafe fn write<'a,T>(&self)->&'a mut[T] {
        if self.length==0 { &mut[] } else { slice::from_raw_parts_mut(self.pointer as *mut T,self.length) }
    }
    fn span<T>(&self)->(usize,usize) { (self.pointer as usize,self.length*mem::size_of::<T>()) }
}
fn disjoint(inputs:&[(usize,usize)],outputs:&[(usize,usize)])->bool {
    outputs.iter().enumerate().all(|(index,&(a,n))| inputs.iter().chain(outputs[..index].iter())
        .all(|&(b,m)| n==0 || m==0 || a+n<=b || b+m<=a))
}
fn offsets(values:&[i64],length:usize)->bool {
    values.first()==Some(&0) && values.last()==Some(&(length as i64))
        && values.windows(2).all(|v|v[0]>=0 && v[0]<=v[1])
}
fn day(value:i32)->bool { value>0 && value<=3652059 }
fn factors(input:&[f64],output:&mut[f64]) {
__FACTORS__
}
__DECISIONS__
#[no_mangle]
pub extern "C" fn candidate_abi()->i32 { ABI }
#[no_mangle]
pub unsafe extern "C" fn candidate_reports(nbooks:usize,nsymbols:usize,nreports:usize,age:i32,
    entries:Buffer,off:Buffer,ids:Buffer,known:Buffer,fiscal:Buffer,out:Buffer)->i32 {
    let Some(n)=nbooks.checked_mul(nsymbols) else{return -1};
    let Some(offset_count)=nsymbols.checked_add(1) else{return -1};
    if age<0 || !entries.valid::<i32>(nbooks) || !off.valid::<i64>(offset_count)
        || !ids.valid::<i32>(ids.length) || !known.valid::<i32>(ids.length)
        || !fiscal.valid::<i32>(ids.length) || !out.valid::<i32>(n) {return -1}
    if !disjoint(&[entries.span::<i32>(),off.span::<i64>(),ids.span::<i32>(),known.span::<i32>(),fiscal.span::<i32>()],&[out.span::<i32>()]) {return -2}
    let entries=entries.read::<i32>();let off=off.read::<i64>();let ids=ids.read::<i32>();
    let known=known.read::<i32>();let fiscal=fiscal.read::<i32>();
    if !offsets(off,ids.len()) || entries.iter().any(|v|!day(*v)) || known.iter().chain(fiscal.iter()).any(|v|!day(*v))
        || ids.iter().any(|v|*v<0 || *v as usize>=nreports) {return -3}
    let out=out.write::<i32>();
    for (book,&entry) in entries.iter().enumerate() {
        for symbol in 0..nsymbols {
            let (begin,end)=(off[symbol] as usize,off[symbol+1] as usize);
            let (mut left,mut right)=(begin,end);
            while left<right {let middle=left+(right-left)/2;if known[middle]<entry {left=middle+1} else {right=middle}}
            out[book*nsymbols+symbol]=if left>begin && i64::from(entry)-i64::from(fiscal[left-1])<=i64::from(age) {ids[left-1]} else {-1};
        }
    }
    0
}
#[no_mangle]
pub unsafe extern "C" fn candidate_prices(n:usize,nsymbols:usize,symbols:Buffer,targets:Buffer,columns:Buffer,forwards:Buffer,
    ro:Buffer,rd:Buffer,rv:Buffer,ao:Buffer,ad:Buffer,av:Buffer,actual:Buffer,values:Buffer)->i32 {
    let Some(noff)=nsymbols.checked_add(1) else{return -1};
    if !symbols.valid::<i32>(n) || !targets.valid::<i32>(n) || !columns.valid::<u8>(n) || !forwards.valid::<u8>(n)
        || !ro.valid::<i64>(noff) || !rd.valid::<i32>(rd.length) || !rv.valid::<f64>(rd.length)
        || !ao.valid::<i64>(noff) || !ad.valid::<i32>(ad.length) || !av.valid::<f64>(ad.length)
        || !actual.valid::<i32>(n) || !values.valid::<f64>(n) {return -1}
    if !disjoint(&[symbols.span::<i32>(),targets.span::<i32>(),columns.span::<u8>(),forwards.span::<u8>(),
        ro.span::<i64>(),rd.span::<i32>(),rv.span::<f64>(),ao.span::<i64>(),ad.span::<i32>(),av.span::<f64>()],
        &[actual.span::<i32>(),values.span::<f64>()]) {return -2}
    let symbols=symbols.read::<i32>();let targets=targets.read::<i32>();let columns=columns.read::<u8>();let forwards=forwards.read::<u8>();
    let ro=ro.read::<i64>();let rd=rd.read::<i32>();let rv=rv.read::<f64>();let ao=ao.read::<i64>();let ad=ad.read::<i32>();let av=av.read::<f64>();
    if !offsets(ro,rd.len()) || !offsets(ao,ad.len()) || symbols.iter().any(|s|*s < -1 || *s>=0 && *s as usize>=nsymbols)
        || targets.iter().any(|v|!day(*v)) || columns.iter().chain(forwards.iter()).any(|v|*v>1) {return -3}
    let actual=actual.write::<i32>();let values=values.write::<f64>();
    for index in 0..n {
        actual[index]=0;values[index]=f64::NAN;
        if symbols[index]<0 {continue}
        let symbol=symbols[index] as usize;
        let (off,history,prices)=if columns[index]==0 {(ro,rd,rv)} else {(ao,ad,av)};
        let (begin,end)=(off[symbol] as usize,off[symbol+1] as usize);
        let (mut left,mut right)=(begin,end);let forward=forwards[index]!=0;
        while left<right {let middle=left+(right-left)/2;
            if history[middle]<targets[index] || (!forward && history[middle]==targets[index]) {left=middle+1} else {right=middle}}
        if forward && left<end {actual[index]=history[left];values[index]=prices[left]}
        else if !forward && left>begin {actual[index]=history[left-1];values[index]=prices[left-1]}
    }
    0
}
#[no_mangle]
pub unsafe extern "C" fn candidate_factors(n:usize,threads:usize,input:Buffer,output:Buffer)->i32 {
    let (Ok(ni),Ok(no))=(checked(n,NI),checked(n,NO)) else{return -1};
    if threads==0 || !input.valid::<f64>(ni) || !output.valid::<f64>(no) {return -1}
    if !disjoint(&[input.span::<f64>()],&[output.span::<f64>()]) {return -2}
    let input=input.read::<f64>();let output=output.write::<f64>();
    if n==0 {return 0}
    let chunk=n.div_ceil(threads.min(n));
    let joined=std::thread::scope(|scope| {
        let mut handles=Vec::new();
        for (index,part) in output.chunks_mut(chunk*NO).enumerate() {
            handles.push(scope.spawn(move || {
                #[cfg(test)] lifetime_tests::touch();
                for row in 0..part.len()/NO {
                let start=(index*chunk+row)*NI;factors(&input[start..start+NI],&mut part[row*NO..(row+1)*NO]);
            }}));
        }
        // Automatic scope joining need not finish TLS destructors. An explicit
        // join owns the complete OS thread lifetime before DLL unload is safe.
        let mut okay=true;
        for handle in handles {okay=handle.join().is_ok() && okay;}
        okay
    });
    if !joined {return -4}
    0
}
#[no_mangle]
pub unsafe extern "C" fn candidate_materialize(n:usize,threads:usize,first:i64,days:Buffer,prices:Buffer,numeric:Buffer,meta:Buffer,matrix:Buffer,
    requested:Buffer,identities:Buffer,dates:Buffer,values:Buffer,flags:Buffer,count:Buffer)->i32 {
    let (Ok(n7),Ok(n6),Ok(ni),Ok(no),Ok(n4),Ok(nv),Ok(nf))=(checked(n,7),checked(n,6),checked(n,NI),checked(n,NO),checked(n,4),checked(n,WIDTH),checked(n,FLAGS)) else{return -1};
    if threads==0 || first<0 || i64::try_from(n).ok().and_then(|v|first.checked_add(v)).is_none()
        || !days.valid::<i32>(n7) || !prices.valid::<f64>(n7) || !numeric.valid::<f64>(no)
        || !meta.valid::<i32>(n6) || !matrix.valid::<f64>(ni) || !requested.valid::<u8>(NF)
        || !identities.valid::<i64>(n) || !dates.valid::<i32>(n4) || !values.valid::<f64>(nv)
        || !flags.valid::<u8>(nf) || !count.valid::<i64>(1) {return -1}
    if !disjoint(&[days.span::<i32>(),prices.span::<f64>(),numeric.span::<f64>(),meta.span::<i32>(),matrix.span::<f64>(),requested.span::<u8>()],
        &[identities.span::<i64>(),dates.span::<i32>(),values.span::<f64>(),flags.span::<u8>(),count.span::<i64>()]) {return -2}
    let days=days.read::<i32>();let prices=prices.read::<f64>();let numeric=numeric.read::<f64>();let meta=meta.read::<i32>();let matrix=matrix.read::<f64>();let requested=requested.read::<u8>();
    if days.iter().any(|d|*d!=0 && !day(*d)) || requested.iter().any(|v|*v>1)
        || meta.chunks_exact(6).any(|m|!day(m[0]) || !day(m[1]) || !day(m[2]) || m[3]<1 || m[3]>9999 || m[4]<1 || m[4]>9999 || m[5]<0 || m[5]>1) {return -3}
    let ids=identities.write::<i64>();let dates=dates.write::<i32>();let values=values.write::<f64>();let flags=flags.write::<u8>();let count=count.write::<i64>();
    if n==0 {count[0]=0;return 0}
    let chunk=n.div_ceil(threads.min(n));
    let joined=std::thread::scope(|scope| {
        let mut handles=Vec::new();
        for (index,(((id,dt),val),flag)) in ids.chunks_mut(chunk).zip(dates.chunks_mut(chunk*4)).zip(values.chunks_mut(chunk*WIDTH)).zip(flags.chunks_mut(chunk*FLAGS)).enumerate() {
            handles.push(scope.spawn(move || {
                #[cfg(test)] lifetime_tests::touch();
                for row in 0..id.len() {
                let original=index*chunk+row;id[row]=first+original as i64;
                let dt=&mut dt[row*4..(row+1)*4];let val=&mut val[row*WIDTH..(row+1)*WIDTH];let flag=&mut flag[row*FLAGS..(row+1)*FLAGS];
                dt.fill(0);val.fill(f64::NAN);flag.fill(0);
                let m=&meta[original*6..(original+1)*6];let num=&numeric[original*NO..(original+1)*NO];let input=&matrix[original*NI..(original+1)*NI];
                let decided=decision_snapshot(&days[original*7..(original+1)*7],&prices[original*7..(original+1)*7],num,
                    m[0] as f64,m[1] as f64,m[2] as f64,m[3] as f64,m[4] as f64,input[__BANKRUPTCY__]);
                if decided[0]!=0.0 && decision_eligible(num,m[5] as f64) {
                    flag[0]=1;for c in 0..4 {dt[c]=decided[c+1] as i32}
                    for c in 0..11 {val[c]=num[COLS[c]]}
                    let average=input[__AVERAGE__];flag[1]=decision_current(num,average,!average.is_nan()) as u8;flag[2]=decision_three(num,average,!average.is_nan()) as u8;
                    for c in 0..NF {let v=num[COLS[11+c]];if requested[c]!=0 && v.is_finite() {val[11+c]=v;flag[3+c]=1}}
                }
            }}));
        }
        // Automatic scope joining need not finish TLS destructors. An explicit
        // join owns the complete OS thread lifetime before DLL unload is safe.
        let mut okay=true;
        for handle in handles {okay=handle.join().is_ok() && okay;}
        okay
    });
    if !joined {return -4}
    count[0]=flags.chunks_exact(FLAGS).filter(|v|v[0]!=0).count() as i64;
    0
}


#[cfg(test)]
mod lifetime_tests {
    use super::*;
    use std::sync::atomic::{AtomicBool,AtomicUsize,Ordering};
    static STARTED:AtomicUsize=AtomicUsize::new(0);
    static FINISHED:AtomicUsize=AtomicUsize::new(0);
    static RELEASE:AtomicBool=AtomicBool::new(true);
    struct Marker;
    impl Drop for Marker {
        fn drop(&mut self) {
            STARTED.fetch_add(1,Ordering::SeqCst);
            while !RELEASE.load(Ordering::SeqCst) {std::thread::sleep(std::time::Duration::from_millis(1));}
            FINISHED.fetch_add(1,Ordering::SeqCst);
        }
    }
    thread_local! {static MARKER:Marker=const {Marker};}
    pub(super) fn touch() {MARKER.with(|_|{});}
    fn buffer<T>(values:&mut[T])->Buffer {Buffer{pointer:values.as_mut_ptr() as *mut u8,length:values.len()}}
    fn gated(operation:impl FnOnce()+Send+'static) {
        use std::time::{Duration,Instant};
        STARTED.store(0,Ordering::SeqCst);FINISHED.store(0,Ordering::SeqCst);
        RELEASE.store(false,Ordering::SeqCst);
        let (send,receive)=std::sync::mpsc::channel();
        let caller=std::thread::spawn(move || {operation();send.send(()).unwrap();});
        let deadline=Instant::now()+Duration::from_secs(10);
        while STARTED.load(Ordering::SeqCst)!=2 && Instant::now()<deadline {
            std::thread::sleep(Duration::from_millis(1));
        }
        let started=STARTED.load(Ordering::SeqCst);
        // Native worker destructors are now blocked on our gate. A separate
        // caller can only signal completion after the ABI has actually returned.
        let early=receive.recv_timeout(Duration::from_millis(100)).is_ok();
        RELEASE.store(true,Ordering::SeqCst);
        caller.join().unwrap();
        let deadline=Instant::now()+Duration::from_secs(10);
        while FINISHED.load(Ordering::SeqCst)!=2 && Instant::now()<deadline {
            std::thread::sleep(Duration::from_millis(1));
        }
        assert_eq!(started,2,"Native workers did not reach the controlled TLS gate");
        assert!(!early,"ABI returned while native TLS destructors were blocked");
        complete();
    }
    fn complete() {
        assert_eq!(STARTED.load(Ordering::SeqCst),2);
        assert_eq!(FINISHED.load(Ordering::SeqCst),2,"ABI returned before native TLS destructors completed");
    }
    #[test]
    fn tls_destructors_finish_before_return() {
        gated(|| {
            let n=8;let mut input=vec![1.0;n*NI];let mut numeric=vec![0.0;n*NO];
            assert_eq!(unsafe{candidate_factors(n,2,buffer(&mut input),buffer(&mut numeric))},0);
        });
        gated(|| {
            let n=8;let mut input=vec![1.0;n*NI];let mut numeric=vec![1.0;n*NO];
            let mut days=vec![1_i32;n*7];let mut prices=vec![1.0;n*7];
            let mut meta=Vec::new();for _ in 0..n {meta.extend([1_i32,1,2,1,1,0]);}
            let mut requested=vec![1_u8;NF];let mut ids=vec![0_i64;n];let mut dates=vec![0_i32;n*4];
            let mut values=vec![0.0;n*WIDTH];let mut flags=vec![0_u8;n*FLAGS];let mut count=vec![0_i64];
            assert_eq!(unsafe{candidate_materialize(n,2,0,buffer(&mut days),buffer(&mut prices),buffer(&mut numeric),
                buffer(&mut meta),buffer(&mut input),buffer(&mut requested),buffer(&mut ids),buffer(&mut dates),
                buffer(&mut values),buffer(&mut flags),buffer(&mut count))},0);
        });
    }
}
